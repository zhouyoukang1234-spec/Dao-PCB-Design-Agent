"""eprj2_codec — 嘉立创EDA Pro `.eprj2` 工程文件本源编解码器。

逆向定界（本会话三层序列化模型 + 字节级回写实证）：
  1) **加密 op-log（落盘日志态）**：`history_data.dataStr` 每行是一个文档的
     源记录流（`{"type":TAG}||{payload}|` 形式，与 `getDocumentSource` 同构），
     经 **gzip(level1) → AES-128-GCM → base64** 落盘。
       - key = 该分支 `project_history_<branch>.key`（16 字节，hex）
       - iv  = 该 history 行 `uuid` 的 hex 前缀（16 字节；`-N` 后缀非 hex 被截断，
               故同一文档多段共用 IV —— 这正解释了各段密文前缀相同）
       - 明文 = gzip 解压后的源记录流；密文 = AES-GCM(ct)||tag(16B)
  2) **materialized 明文态**：`documents.dataStr` / `coppers` / `texts` 等是
     另一套 `["TYPE",...]` 换行 JSON 数组格式（保存/分发态快照，便携可读）。
  3) **export 态**：`sys_FileManager.getDocumentSource` 是只读导出的 live 序列化。

本模块实现 op-log 层的 **解密/加密对称编解码**（加解密 round-trip 已实证无损）。
**它是真正的 READ 原语**：可零 GUI 直读任意 `.eprj2` 的全量 live 源记录流。

⚠ **WRITE 边界（本会话字节级双实证·诚实定界）**：直接改写落盘 op-log 不构成
  「程控直写 PCB 文件」的有效写路径。在同一文件（`getCurrentProjectInfo` 确认
  打开的就是被改文件）、排除一切外部态（`web.db`/IndexedDB/recovery/`snapshot`
  均空）、kill+relaunch 清空内存的前提下：
    - 改 NET 名 `VCC→DAOPWR`、改纯 PCB 几何 `"Top Layer"→"DAOTOPXX"` 两次实验，
    - 改动均**持久留在文件**（重开后 op-log 行仍是新值、未被回写覆盖），
    - 但重开后的 live 文档**仍是原值**（`getDocumentSource` 不含新值）。
  ∴ 编辑器 open 时的加载态**并非对落盘 op-log 的重放**；`.eprj2` 不是直写权威面。
  程控写仍须走 typed RPC primitive（已用其构建全 14 板 battery，DRC=0 CLEAN）。

加密方案取自 app.js `class m4`（aes-128-gcm；encrypt(ivHex, plaintext) =
gzipSync(level1) 后 GCM，附 16B authTag；decrypt 取末 16B 为 tag）。
"""
import base64
import glob
import gzip
import os
import sqlite3

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TAG_LEN = 16


def _hex_prefix(s):
    """取字符串的 hex 前缀（Node `Buffer.from(s,'hex')` 语义：遇非 hex 即止）。"""
    out = []
    for ch in s:
        if ch in "0123456789abcdefABCDEF":
            out.append(ch)
        else:
            break
    h = "".join(out)
    if len(h) % 2:
        h = h[:-1]
    return h


def key_map(con):
    """映射 {history_uuid: key}。

    每个 `project_history_<branch>` 表按 `uuid` 存多个文档/版本的 key；
    `history_data.history_uuid` 即指向该 uuid。各行需用**匹配的** key 解密。"""
    m = {}
    for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'project_history_%'"):
        for uuid, key in con.execute(
                "SELECT uuid,key FROM '%s' WHERE key IS NOT NULL" % t):
            m[uuid] = key
    if not m:
        raise RuntimeError("no encryption key in project_history_* tables")
    return m


def branch_key(con):
    """兑容：返回任一 key（单分支单文档工程适用）。"""
    return next(iter(key_map(con).values()))


def decrypt_blob(key_hex, iv_source, b64data):
    """解密单条 op-log：key_hex/iv_source(hex 前缀)/base64 密文 → 明文源记录流。"""
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(_hex_prefix(iv_source))
    blob = base64.b64decode(b64data)
    pt_gz = AESGCM(key).decrypt(iv, blob, None)  # blob = ct||tag(16)
    return gzip.decompress(pt_gz).decode("utf-8", "replace")


def encrypt_blob(key_hex, iv_source, plaintext):
    """加密单条 op-log（与 app.js 对称）：明文 → base64(GCM(gzip(pt))||tag)。

    注：Node gzipSync(level1) 与 Python 字节未必逐字节相同，但 GCM tag 覆盖的是
    本函数自产的密文、解密侧只需 gunzip 任意合法 gzip 流，故 LCEDA 可正常读回。
    """
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(_hex_prefix(iv_source))
    gz = gzip.compress(plaintext.encode("utf-8"), compresslevel=1)
    blob = AESGCM(key).encrypt(iv, gz, None)  # 返回 ct||tag(16)
    return base64.b64encode(blob).decode("ascii")


def split_records(plaintext):
    """把源记录流拆成 [(tag, head_json, payload_json), ...]。

    形如 `{"type":TAG, ..}||{payload}|`（` |` 分隔记录、`||` 分隔头/载荷）。
    返回原样片段以便无损改写；只解析最外层。"""
    recs = []
    for chunk in plaintext.split("|\n") if "|\n" in plaintext else plaintext.split("| "):
        c = chunk.strip().rstrip("|").strip()
        if not c:
            continue
        recs.append(c)
    return recs


def iter_history(con):
    """遍历 history_data：返回 [(id, uuid, history_uuid, plaintext)]（已解密）。"""
    km = key_map(con)
    out = []
    for rid, uuid, huid, ds in con.execute(
            "SELECT id,uuid,history_uuid,dataStr FROM history_data ORDER BY id"):
        out.append((rid, uuid, huid, decrypt_blob(km[huid], uuid, ds)))
    return out


def write_history(con, row_id, uuid, history_uuid, plaintext):
    """把明文重新加密写回指定 history_data 行（用该行 history_uuid 对应的 key、iv=uuid）。"""
    key = key_map(con)[history_uuid]
    b64 = encrypt_blob(key, uuid, plaintext)
    con.execute("UPDATE history_data SET dataStr=? WHERE id=?", (b64, row_id))


def open_eprj2(path):
    return sqlite3.connect(path)


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else sorted(
        glob.glob(os.path.expanduser(
            "~/Documents/LCEDA-Pro/projects/*.eprj2")))[-1]
    con = open_eprj2(p)
    print("file:", os.path.basename(p))
    for rid, uuid, huid, plain in iter_history(con):
        head = plain[:120].replace("\n", " ")
        # 第二条记录通常是 DOCHEAD，含 docType
        dt = ""
        if '"docType"' in plain:
            i = plain.find('"docType"')
            dt = plain[i:i + 40]
        print("  id=%-2d len=%-7d %s | %s" % (rid, len(plain), dt, head[:70]))
