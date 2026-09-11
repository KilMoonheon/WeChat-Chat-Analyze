"""微信 4.x WCDB 数据库密钥提取与解密（基于 wcdb-key-tool，MIT License）。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import hashlib
import hmac as hmac_mod
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80
SQLITE_HDR = b"SQLite format 3\x00"

_HEX_RE = re.compile(rb"x'([0-9a-fA-F]{64,192})'")
WINDOWS_CONFIG_CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
WINDOWS_CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b"
    "450048844c2448488944254048584c24"
)
WINDOWS_MAX_USER_ADDRESS = 0x0000_8000_0000_0000
WINDOWS_CONFIG_BLOB_MAX = 1024
WINDOWS_CONFIG_LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")

_bcrypt = ctypes.WinDLL("bcrypt")
_bcrypt.BCryptOpenAlgorithmProvider.argtypes = [
    ctypes.POINTER(wt.HANDLE), ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong
]
_bcrypt.BCryptSetProperty.argtypes = [wt.HANDLE, ctypes.c_wchar_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong]
_bcrypt.BCryptGenerateSymmetricKey.argtypes = [
    wt.HANDLE, ctypes.POINTER(wt.HANDLE), ctypes.c_char_p, ctypes.c_ulong,
    ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong,
]
_bcrypt.BCryptDecrypt.argtypes = [
    wt.HANDLE, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_void_p,
    ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong,
]


def _print(*args, **kwargs):
    print(*args, flush=True, **kwargs)


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    h_alg = wt.HANDLE()
    status = _bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), "AES", None, 0)
    if status != 0:
        raise RuntimeError(f"BCryptOpenAlgorithmProvider failed: {status:#x}")
    try:
        mode = ("ChainingModeCBC\x00").encode("utf-16-le")
        status = _bcrypt.BCryptSetProperty(h_alg, "ChainingMode", mode, len(mode), 0)
        if status != 0:
            raise RuntimeError(f"BCryptSetProperty failed: {status:#x}")
        h_key = wt.HANDLE()
        status = _bcrypt.BCryptGenerateSymmetricKey(h_alg, ctypes.byref(h_key), None, 0, key, len(key), 0)
        if status != 0:
            raise RuntimeError(f"BCryptGenerateSymmetricKey failed: {status:#x}")
        try:
            iv_buf = ctypes.create_string_buffer(iv, len(iv))
            out_buf = ctypes.create_string_buffer(len(data))
            result_len = ctypes.c_ulong(0)
            status = _bcrypt.BCryptDecrypt(
                h_key, data, len(data), None,
                iv_buf, len(iv), out_buf, len(out_buf), ctypes.byref(result_len), 0,
            )
            if status != 0:
                raise RuntimeError(f"BCryptDecrypt failed: {status:#x}")
            return out_buf.raw[: result_len.value]
        finally:
            _bcrypt.BCryptDestroyKey(h_key)
    finally:
        _bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)


def verify_enc_key(enc_key: bytes, db_page1: bytes) -> bool:
    salt = db_page1[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hmac_data = db_page1[SALT_SZ: PAGE_SZ - 80 + 16]
    stored_hmac = db_page1[PAGE_SZ - 64: PAGE_SZ]
    hm = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    hm.update(struct.pack("<I", 1))
    return hm.digest() == stored_hmac


def collect_db_files(db_dir: str) -> tuple[list, dict]:
    db_files: list = []
    salt_to_dbs: dict[str, list[str]] = {}
    for root, _dirs, files in os.walk(db_dir):
        for name in files:
            if not name.endswith(".db") or name.endswith("-wal") or name.endswith("-shm"):
                continue
            path = os.path.join(root, name)
            size = os.path.getsize(path)
            if size < PAGE_SZ:
                continue
            with open(path, "rb") as f:
                page1 = f.read(PAGE_SZ)
            rel = os.path.relpath(path, db_dir)
            salt = page1[:SALT_SZ].hex()
            db_files.append((rel, path, size, salt, page1))
            salt_to_dbs.setdefault(salt, []).append(rel)
    return db_files, salt_to_dbs


def auto_detect_db_dir() -> str | None:
    appdata = os.environ.get("APPDATA", "")
    config_dir = os.path.join(appdata, "Tencent", "xwechat", "config")
    data_roots: list[str] = []
    if os.path.isdir(config_dir):
        for ini_file in glob.glob(os.path.join(config_dir, "*.ini")):
            for enc in ("utf-8", "gbk"):
                try:
                    with open(ini_file, "r", encoding=enc) as f:
                        content = f.read(1024).strip()
                    if content and os.path.isdir(content):
                        data_roots.append(content)
                    break
                except UnicodeDecodeError:
                    continue
    candidates: list[str] = []
    for root in data_roots:
        for match in glob.glob(os.path.join(root, "xwechat_files", "*", "db_storage")):
            if os.path.isdir(match) and match not in candidates:
                candidates.append(match)
    default = os.path.join(os.path.expanduser("~"), "Documents", "xwechat_files", "*", "db_storage")
    for match in glob.glob(default):
        if os.path.isdir(match) and match not in candidates:
            candidates.append(match)
    return candidates[0] if candidates else None


def _get_pids_windows() -> list[tuple[int, int]]:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    pids: list[tuple[int, int]] = []
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        p = line.strip('"').split('","')
        if len(p) >= 5:
            pid = int(p[1])
            mem = int(p[4].replace(",", "").replace(" K", "").strip() or "0")
            pids.append((pid, mem))
    if not pids:
        raise RuntimeError("Weixin.exe 未运行，请先启动微信 PC 版")
    pids.sort(key=lambda x: x[1], reverse=True)
    for pid, mem in pids:
        _print(f"[+] Weixin.exe PID={pid} ({mem // 1024}MB)")
    return pids


def _xor_repeat(data: bytes, mask: bytes) -> bytes:
    return bytes(value ^ mask[index % len(mask)] for index, value in enumerate(data))


def _u64_from(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        return 0
    return struct.unpack_from("<Q", data, offset)[0]


def _probable_32_byte_key(data: bytes) -> bool:
    return len(data) == KEY_SZ and len(set(data)) >= 15 and data not in {b"\x00" * KEY_SZ, b"\xff" * KEY_SZ}


def _iter_windows_region_chunks(regions, read_region, *, chunk_size=2 * 1024 * 1024, overlap=0):
    for base, size in regions:
        offset = 0
        tail = b""
        tail_base = base
        while offset < size:
            current_size = min(chunk_size, size - offset)
            chunk = read_region(base + offset, current_size) or b""
            data_base = tail_base if tail else base + offset
            data = tail + chunk
            if data:
                yield data_base, data
                if overlap:
                    tail = data[-overlap:]
                    tail_base = data_base + max(0, len(data) - len(tail))
                else:
                    tail = b""
                    tail_base = base + offset + current_size
            else:
                tail = b""
                tail_base = base + offset + current_size
            offset += current_size


def _find_bytes_in_regions(regions, read_region, needle: bytes) -> set[int]:
    addresses: set[int] = set()
    overlap = max(0, len(needle) - 1)
    for data_base, haystack in _iter_windows_region_chunks(regions, read_region, overlap=overlap):
        pos = haystack.find(needle)
        while pos >= 0:
            addresses.add(data_base + pos)
            pos = haystack.find(needle, pos + 1)
    return addresses


def _windows_v411_config_key_candidates(blob: bytes) -> list[tuple[str, str | None]]:
    if not blob or len(blob) > WINDOWS_CONFIG_BLOB_MAX:
        return []
    decoded = _xor_repeat(blob, WINDOWS_CONFIG_XOR_MASK)
    out: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for match in WINDOWS_CONFIG_LITERAL_RE.finditer(decoded):
        run = match.group(1).decode("ascii").lower()
        starts = [0]
        if len(run) > 96:
            starts.extend(range(0, len(run) - 63, 32))
        starts.append(len(run) - 64)
        for start in dict.fromkeys(starts):
            if start < 0 or start + 64 > len(run):
                continue
            enc_key_hex = run[start:start + 64]
            try:
                enc_key = bytes.fromhex(enc_key_hex)
            except ValueError:
                continue
            if not _probable_32_byte_key(enc_key):
                continue
            embedded_salt = run[start + 64:start + 96] if start + 96 <= len(run) else None
            item = (enc_key_hex, embedded_salt)
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _verify_windows_direct_key_candidate(enc_key_hex, embedded_salt, db_files, salt_to_dbs, key_map, remaining_salts) -> int:
    if not remaining_salts:
        return 0
    try:
        enc_key = bytes.fromhex(enc_key_hex)
    except ValueError:
        return 0
    if not _probable_32_byte_key(enc_key):
        return 0
    matched = 0
    target_salts = [embedded_salt] if embedded_salt in remaining_salts else list(remaining_salts)
    for salt_hex in target_salts:
        if salt_hex not in remaining_salts:
            continue
        for _rel, _path, _sz, s, page1 in db_files:
            if s == salt_hex and verify_enc_key(enc_key, page1):
                key_map[salt_hex] = enc_key_hex
                remaining_salts.discard(salt_hex)
                matched += 1
                break
    return matched


def _scan_windows_v411_config_cipher(pid, regions, read_region, read_mem, db_files, salt_to_dbs, key_map, remaining_salts) -> dict:
    stats = {"matched_salts": 0, "candidate_count": 0, "node_candidates": 0}
    needle_addresses = _find_bytes_in_regions(regions, read_region, WINDOWS_CONFIG_CIPHER_NAME)
    if not needle_addresses:
        return stats
    pair_patterns = [
        struct.pack("<Q", addr) + struct.pack("<Q", len(WINDOWS_CONFIG_CIPHER_NAME))
        for addr in needle_addresses
    ]
    seen_candidates: set[tuple[str, str | None]] = set()
    for base, data in _iter_windows_region_chunks(regions, read_region, overlap=0x80):
        if not remaining_salts:
            break
        for pattern in pair_patterns:
            pos = data.find(pattern)
            while pos >= 0:
                qaddr = base + pos
                node = read_mem(qaddr - 0x10, 0x50)
                if node and len(node) >= 0x40:
                    if _u64_from(node, 0x10) in needle_addresses and _u64_from(node, 0x18) == len(WINDOWS_CONFIG_CIPHER_NAME):
                        config_ptr = _u64_from(node, 0x28)
                        if 0x10000 <= config_ptr < WINDOWS_MAX_USER_ADDRESS:
                            stats["node_candidates"] += 1
                            obj = read_mem(config_ptr + 0x88, 0x28)
                            if obj and len(obj) >= 0x18:
                                data_ptr = _u64_from(obj, 0x8)
                                data_len = _u64_from(obj, 0x10)
                                if 0 < data_len <= WINDOWS_CONFIG_BLOB_MAX and 0x10000 <= data_ptr < WINDOWS_MAX_USER_ADDRESS:
                                    blob = read_mem(data_ptr, int(data_len))
                                    if blob and len(blob) == data_len:
                                        for enc_key_hex, embedded_salt in _windows_v411_config_key_candidates(blob):
                                            candidate = (enc_key_hex, embedded_salt)
                                            if candidate in seen_candidates:
                                                continue
                                            seen_candidates.add(candidate)
                                            stats["candidate_count"] += 1
                                            matched = _verify_windows_direct_key_candidate(
                                                enc_key_hex, embedded_salt, db_files, salt_to_dbs, key_map, remaining_salts
                                            )
                                            if matched:
                                                stats["matched_salts"] += matched
                pos = data.find(pattern, pos + 1)
    if stats["matched_salts"]:
        _print(f"[+] Config.Cipher 扫描匹配 {stats['matched_salts']} 个 salt (pid={pid})")
    return stats


def _save_results(db_files, salt_to_dbs, key_map, db_dir, out_file) -> None:
    result: dict = {}
    for rel, _path, sz, salt_hex, _page1 in db_files:
        if salt_hex in key_map:
            result[rel] = {"enc_key": key_map[salt_hex], "salt": salt_hex, "size_mb": round(sz / 1024 / 1024, 1)}
            _print(f" OK: {rel} ({sz / 1024 / 1024:.1f}MB)")
    if not result:
        raise RuntimeError("未能提取到任何密钥")
    result["_db_dir"] = db_dir
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    _print(f"密钥保存到: {out_file}")


def scan_memory_keys(db_dir: str, keys_file: str) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("密钥提取仅支持 Windows")
    db_files, salt_to_dbs = collect_db_files(db_dir)
    if not db_files:
        raise RuntimeError(f"在 {db_dir} 未找到可解密的 .db 文件")
    _print(f"找到 {len(db_files)} 个数据库, {len(salt_to_dbs)} 个不同的 salt")

    kernel32 = ctypes.windll.kernel32
    MEM_COMMIT = 0x1000
    READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
            ("AllocationProtect", wt.DWORD), ("_pad1", wt.DWORD),
            ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
            ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_pad2", wt.DWORD),
        ]

    def read_mem(h, addr, sz):
        buf = ctypes.create_string_buffer(sz)
        n = ctypes.c_size_t(0)
        if kernel32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, sz, ctypes.byref(n)):
            return buf.raw[: n.value]
        return None

    def enum_regions(h):
        regs = []
        addr = 0
        mbi = MBI()
        while addr < 0x7FFFFFFFFFFF:
            if kernel32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
                break
            if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and 0 < mbi.RegionSize < 500 * 1024 * 1024:
                regs.append((mbi.BaseAddress, mbi.RegionSize))
            nxt = mbi.BaseAddress + mbi.RegionSize
            if nxt <= addr:
                break
            addr = nxt
        return regs

    pids = _get_pids_windows()
    key_map: dict[str, str] = {}
    remaining_salts = set(salt_to_dbs.keys())
    t0 = time.time()

    for pid, _mem_kb in pids:
        h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not h:
            _print(f"[WARN] 无法打开进程 PID={pid}，尝试以管理员身份运行")
            continue
        try:
            regions = enum_regions(h)
            _scan_windows_v411_config_cipher(
                pid, regions,
                lambda base, size, _h=h: read_mem(_h, base, size),
                lambda addr, size, _h=h: read_mem(_h, addr, size),
                db_files, salt_to_dbs, key_map, remaining_salts,
            )
        finally:
            kernel32.CloseHandle(h)
        if not remaining_salts:
            break

    if not remaining_salts:
        _save_results(db_files, salt_to_dbs, key_map, db_dir, keys_file)
        return key_map

    for pid, _mem_kb in pids:
        h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not h:
            continue
        try:
            for base, size in enum_regions(h):
                if not remaining_salts:
                    break
                data = read_mem(h, base, size)
                if not data:
                    continue
                for m in _HEX_RE.finditer(data):
                    hex_str = m.group(1).decode()
                    if len(hex_str) < 96:
                        continue
                    enc_key_hex, salt_hex = hex_str[:64], hex_str[64:96]
                    if salt_hex not in remaining_salts:
                        continue
                    enc_key = bytes.fromhex(enc_key_hex)
                    for _rel, _path, _sz, s, page1 in db_files:
                        if s == salt_hex and verify_enc_key(enc_key, page1):
                            key_map[salt_hex] = enc_key_hex
                            remaining_salts.discard(salt_hex)
                            _print(" [FOUND] verified key material")
                            break
        finally:
            kernel32.CloseHandle(h)
        if not remaining_salts:
            break

    _print(f"扫描完成: {time.time() - t0:.1f}s")
    if not key_map:
        raise RuntimeError("未能从进程内存提取到密钥，请以管理员身份运行并重试")
    _save_results(db_files, salt_to_dbs, key_map, db_dir, keys_file)
    return key_map


def _strip_key_metadata(keys: dict) -> dict:
    return {k: v for k, v in keys.items() if not k.startswith("_")}


def _get_key_info(keys: dict, rel_path: str) -> dict | None:
    normalized = rel_path.replace("\\", "/")
    for candidate in (rel_path, normalized, normalized.replace("/", "\\"), normalized.replace("/", os.sep)):
        if candidate in keys and not candidate.startswith("_"):
            return keys[candidate]
    return None


def _decrypt_page(enc_key: bytes, page_data: bytes, pgno: int) -> bytes:
    iv = page_data[PAGE_SZ - RESERVE_SZ: PAGE_SZ - RESERVE_SZ + IV_SZ]
    if pgno == 1:
        encrypted = page_data[SALT_SZ: PAGE_SZ - RESERVE_SZ]
        decrypted = aes_cbc_decrypt(enc_key, iv, encrypted)
        return bytes(SQLITE_HDR + decrypted + b"\x00" * RESERVE_SZ)
    encrypted = page_data[: PAGE_SZ - RESERVE_SZ]
    decrypted = aes_cbc_decrypt(enc_key, iv, encrypted)
    return decrypted + b"\x00" * RESERVE_SZ


def _decrypt_database(db_path: str, out_path: str, enc_key: bytes) -> bool:
    file_size = os.path.getsize(db_path)
    total_pages = file_size // PAGE_SZ
    if file_size % PAGE_SZ != 0:
        total_pages += 1

    with open(db_path, "rb") as fin:
        page1 = fin.read(PAGE_SZ)
        if len(page1) < PAGE_SZ:
            return False
        salt = page1[:SALT_SZ]
        mac_salt = bytes(b ^ 0x3A for b in salt)
        mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
        p1_hmac_data = page1[SALT_SZ: PAGE_SZ - RESERVE_SZ + IV_SZ]
        p1_stored_hmac = page1[PAGE_SZ - HMAC_SZ: PAGE_SZ]
        hm = hmac_mod.new(mac_key, p1_hmac_data, hashlib.sha512)
        hm.update(struct.pack("<I", 1))
        if hm.digest() != p1_stored_hmac:
            _print(f" [ERROR] HMAC 验证失败: {os.path.basename(db_path)}")
            return False

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(db_path, "rb") as fin, open(out_path, "wb") as fout:
        for pgno in range(1, total_pages + 1):
            page = fin.read(PAGE_SZ)
            if len(page) < PAGE_SZ:
                if len(page) > 0:
                    page = page + b"\x00" * (PAGE_SZ - len(page))
                else:
                    break
            fout.write(_decrypt_page(enc_key, page, pgno))
    return True


def decrypt_all(db_dir: str, out_dir: str, keys_file: str) -> dict:
    if not os.path.exists(keys_file):
        raise RuntimeError(f"密钥文件不存在: {keys_file}")
    with open(keys_file, encoding="utf-8") as f:
        keys = _strip_key_metadata(json.load(f))

    os.makedirs(out_dir, exist_ok=True)
    db_files: list[tuple[str, str, int]] = []
    for root, _dirs, files in os.walk(db_dir):
        for fname in files:
            if fname.endswith(".db") and not fname.endswith("-wal") and not fname.endswith("-shm"):
                path = os.path.join(root, fname)
                rel = os.path.relpath(path, db_dir)
                db_files.append((rel, path, os.path.getsize(path)))
    db_files.sort(key=lambda x: x[2])

    success = failed = 0
    for rel, path, sz in db_files:
        key_info = _get_key_info(keys, rel)
        if not key_info:
            failed += 1
            continue
        enc_key = bytes.fromhex(key_info["enc_key"])
        out_path = os.path.join(out_dir, rel)
        _print(f"解密: {rel} ({sz / 1024 / 1024:.1f}MB) ...", end=" ")
        if _decrypt_database(path, out_path, enc_key):
            _print("OK")
            success += 1
        else:
            failed += 1

    _print(f"解密结果: {success} 成功, {failed} 失败")
    return {"success": success, "failed": failed, "total": len(db_files)}
