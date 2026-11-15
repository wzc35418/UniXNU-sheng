/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/vnode.h>
#include <sys/uio.h>
#include <sys/fcntl.h>
#include <sys/kauth.h>
#include <IOKit/IOLib.h>
#include "WifiFirmware.h"

/* Set by the first overlay mount, after every Data addon file is installed. */
extern volatile int native_gpu_addon_stage;

/* The three WCN7850 binaries stay local in a repository build (firmware/README.md), so an image built
 * without them carries only the service. This second source reads them from the board's own storage
 * partition: the archive below is written past the root image and before the Data store, and the UFS
 * driver reads it in place, so neither the boot image nor the Data volume has to grow. */
#define SHENG_WIFI_FW_PARTITION "linux"
#define SHENG_WIFI_FW_BASE (18ull * 1024 * 1024 * 1024)
#define SHENG_WIFI_FW_MAGIC "SHWFW01"
#define SHENG_WIFI_FW_BLOCK 4096u
#define SHENG_WIFI_FW_MAX_ENTRIES 6
#define SHENG_WIFI_FW_MAX_BYTES (32u * 1024 * 1024)

struct sheng_wifi_fw_entry {
  char name[24];
  uint64_t offset;
  uint64_t size;
};

struct sheng_wifi_fw_header {
  char magic[8];
  uint32_t count;
  uint32_t reserved;
  struct sheng_wifi_fw_entry entries[SHENG_WIFI_FW_MAX_ENTRIES];
};

extern int native_ufs_part_find(const char *name, uint32_t *lun, uint64_t *first,
                                uint64_t *blocks) __attribute__((weak_import));
extern int native_ufs_part_read(uint32_t lun, uint64_t lba, uint32_t blocks,
                                void *dst) __attribute__((weak_import));

/* Bytes of the archive: whole blocks straight into to, the ends of a range through one block. */
static int firmwareRead(uint32_t lun, uint64_t first, uint64_t offset, uint8_t *to, size_t length) {
  while (length) {
    const uint64_t lba = offset / SHENG_WIFI_FW_BLOCK;
    const size_t within = (size_t)(offset % SHENG_WIFI_FW_BLOCK);
    if (!within && length >= SHENG_WIFI_FW_BLOCK) {
      uint32_t blocks = (uint32_t)(length / SHENG_WIFI_FW_BLOCK);
      if (blocks > 256) blocks = 256;
      if (!native_ufs_part_read(lun, first + lba, blocks, to)) return EIO;
      const size_t bytes = (size_t)blocks * SHENG_WIFI_FW_BLOCK;
      to += bytes; offset += bytes; length -= bytes;
    } else {
      uint8_t block[SHENG_WIFI_FW_BLOCK];
      if (!native_ufs_part_read(lun, first + lba, 1, block)) return EIO;
      size_t take = SHENG_WIFI_FW_BLOCK - within;
      if (take > length) take = length;
      memcpy(to, block + within, take);
      to += take; offset += take; length -= take;
    }
  }
  return 0;
}

/* 0 with the buffer when the archive carries name; ENOENT when it does not hold it. */
static int firmwareFromPartition(const char *name, uint8_t **data, size_t *size) {
  *data = NULL; *size = 0;
  if (!native_ufs_part_find || !native_ufs_part_read) return ENXIO;
  uint32_t lun = 0; uint64_t first = 0, blocks = 0;
  if (!native_ufs_part_find(SHENG_WIFI_FW_PARTITION, &lun, &first, &blocks)) return ENXIO;
  const uint64_t partitionBytes = blocks * (uint64_t)SHENG_WIFI_FW_BLOCK;
  if (partitionBytes < SHENG_WIFI_FW_BASE + sizeof(struct sheng_wifi_fw_header)) return ENXIO;
  struct sheng_wifi_fw_header header;
  int rc = firmwareRead(lun, first, SHENG_WIFI_FW_BASE, (uint8_t *)&header, sizeof header);
  if (rc) return rc;
  if (memcmp(header.magic, SHENG_WIFI_FW_MAGIC, sizeof header.magic)) return ENOENT;
  if (header.count > SHENG_WIFI_FW_MAX_ENTRIES) return EINVAL;
  for (uint32_t i = 0; i < header.count; i++) {
    const struct sheng_wifi_fw_entry *entry = &header.entries[i];
    if (strncmp(entry->name, name, sizeof entry->name)) continue;
    if (!entry->size || entry->size > SHENG_WIFI_FW_MAX_BYTES) return EINVAL;
    if (SHENG_WIFI_FW_BASE + entry->offset + entry->size > partitionBytes) return EINVAL;
    uint8_t *buffer = IOMallocData((size_t)entry->size);
    if (!buffer) return ENOMEM;
    rc = firmwareRead(lun, first, SHENG_WIFI_FW_BASE + entry->offset, buffer,
                      (size_t)entry->size);
    if (rc) { IOFreeData(buffer, (size_t)entry->size); return rc; }
    *data = buffer; *size = (size_t)entry->size;
    return 0;
  }
  return ENOENT;
}

/* Called on the wireless worker after the Data addon becomes available.
 * Successful ownership is transferred to its boot-lifetime firmware cache. */
int sheng_wifi_firmware_read(const char *name, uint8_t **data, size_t *size) {
  *data = NULL; *size = 0;
  /* join.txt: the unattended-test network file, present only in a build made with UNIXNU_WIFI_JOIN and read only with wifi-aj=1. */
  if (strcmp(name, "amss.bin") && strcmp(name, "amss2.bin") &&
      strcmp(name, "m3.bin") && strcmp(name, "board-2.bin") && strcmp(name, "join.txt")) return ENOENT;
  const bool join = !strcmp(name, "join.txt");
  if (!join) {
    /* The storage archive first: it is present whether or not the addon carries the binaries, so a
     * payload built without them still brings the module up. EAGAIN below asks for a later retry. */
    int rc = firmwareFromPartition(name, data, size);
    if (!rc) return 0;
    if (native_gpu_addon_stage < 1) return EAGAIN;
  } else if (native_gpu_addon_stage < 1) {
    return EAGAIN;
  }
  char path[160]; snprintf(path, sizeof(path), "%s/%s", SHENG_WIFI_FIRMWARE_ROOT, name);
  vfs_context_t ctx = vfs_context_kernel(); vnode_t vp = NULL;
  int error = vnode_open(path, FREAD, 0, 0, &vp, ctx);
  uint8_t *buffer = NULL; size_t length = 0;
  if (!error) {
    struct vnode_attr va; VATTR_INIT(&va); VATTR_WANTED(&va, va_data_size);
    error = vnode_getattr(vp, &va, ctx);
    if (!error && (vnode_vtype(vp) != VREG || !va.va_data_size || va.va_data_size > 32u * 1024 * 1024)) error = EINVAL;
    if (!error) {
      length = (size_t)va.va_data_size; buffer = IOMallocData(length);
      if (!buffer) error = ENOMEM;
      else {
        int resid = 0;
        error = vn_rdwr(UIO_READ, vp, (caddr_t)buffer, (int)length, 0, UIO_SYSSPACE,
            IO_NOAUTH, vfs_context_ucred(ctx), &resid, vfs_context_proc(ctx));
        if (!error && resid) error = EIO;
      }
    }
  }
  if (vp) vnode_close(vp, FREAD, ctx);
  if (error) { if (buffer) IOFreeData(buffer, length); return error; }
  *data = buffer; *size = length; return 0;
}
