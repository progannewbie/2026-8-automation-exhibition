"""
SmartCook 連線排錯工具 (Connection Test)
只測試 TCP 連線 + 握手 + 心跳，跟 F60_F_連線測試.as / F60_R_連線測試.as 配對使用。
不牽涉 comms_connection_skeleton.py 或其他模組，方便獨立驗證通訊層。

用法:
    python connection_test.py --ip 192.168.5.2          # 連 F60_F
    python connection_test.py --ip 192.168.5.7           # 連 F60_R
    python connection_test.py --ip 192.168.5.2 --port 9000
    python connection_test.py --ip 192.168.5.2 --interactive   # 連上後手動輸入訊息互動
"""

import argparse
import socket
import sys
import time


def recv_line(sock: socket.socket, timeout: float = 5.0) -> str:
    """讀取一行 (以 \\n 結尾)，逾時或斷線會丟出例外"""
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(255)
        if not chunk:
            raise ConnectionError("連線已被對方關閉")
        buf += chunk
    line, _, _ = buf.partition(b"\n")
    return line.decode("utf-8", errors="replace")


def send_line(sock: socket.socket, msg: str) -> None:
    sock.sendall((msg + "\n").encode("utf-8"))


def run_handshake(sock: socket.socket) -> str:
    print("→ 傳送: connect")
    send_line(sock, "connect")
    reply = recv_line(sock)
    print(f"← 收到: {reply}")
    if not reply.startswith("BOARD_ID,"):
        raise RuntimeError(f"握手格式不對，預期 'BOARD_ID,<id>'，實際收到: {reply!r}")
    return reply


def run_heartbeat_check(sock: socket.socket) -> None:
    print("→ 傳送: HEARTBEAT")
    send_line(sock, "HEARTBEAT")
    reply = recv_line(sock)
    print(f"← 收到: {reply}")
    if reply != "HEARTBEAT_ACK":
        print(f"⚠ 預期收到 HEARTBEAT_ACK，實際收到: {reply!r}")


def interactive_loop(sock: socket.socket) -> None:
    print("\n進入互動模式，輸入要送出的內容，Ctrl+C 結束")
    while True:
        try:
            msg = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n結束互動模式")
            return
        if not msg:
            continue
        send_line(sock, msg)
        try:
            reply = recv_line(sock)
            print(f"← 收到: {reply}")
        except (socket.timeout, ConnectionError) as e:
            print(f"✗ 讀取回應失敗: {e}")
            return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="機器人控制器 IP (F60_F: 192.168.5.2 / F60_R: 192.168.5.7)")
    parser.add_argument("--port", type=int, default=9000, help="埠號 (預設 9000)")
    parser.add_argument("--timeout", type=float, default=5.0, help="連線逾時秒數 (預設 5)")
    parser.add_argument("--interactive", action="store_true", help="握手+心跳測試通過後，進入手動輸入互動模式")
    args = parser.parse_args()

    print(f"連線到 {args.ip}:{args.port} ...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(args.timeout)
    try:
        sock.connect((args.ip, args.port))
    except OSError as e:
        print(f"✗ 連線失敗: {e}")
        print("檢查: 1) 控制器程式是否已執行到 TCP_LISTEN 2) IP/埠號是否正確 3) 網路線是否接好")
        return 1
    print("✓ TCP 連線成功")

    try:
        run_handshake(sock)
        print("✓ 握手成功")
        run_heartbeat_check(sock)
        if args.interactive:
            interactive_loop(sock)
    except (RuntimeError, ConnectionError, socket.timeout) as e:
        print(f"✗ 測試失敗: {e}")
        return 1
    finally:
        sock.close()

    print("\n✓ 連線測試全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
