"""
SmartCook 雙臂 I/O 接線測試工具 (IOTEST-Only Test)
跳過整套動作與 SYNC_STEP，直接用 IOTEST,<ON|OFF|READ> 指令操作單一
訊號腳位，確認 F60_F <-> F60_R 之間的 sig_out_step/sig_in_step 實體
接線是否真的接通、方向是否正確。SYNC_STEP 逾時 (E4023) 時，先跑這支
排除是接線問題還是程式邏輯問題。

用法:
    python test_io.py
"""

import sys
import logging
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from comms_connection_skeleton import CommsManager

SETTLE_SEC = 0.3  # 送出 ON/OFF 後，等訊號穩定再去讀對面，避免誤判

logger = logging.getLogger(__name__)


def read_sig(manager: CommsManager, arm_id: str):
    """送 IOTEST,READ，回傳 1 / 0 / None(異常)"""
    resp = manager.send_command(arm_id, "IOTEST,READ")
    if resp == "SIG,1":
        return 1
    if resp == "SIG,0":
        return 0
    print(f"    ! {arm_id} IOTEST,READ 回應異常: {resp}")
    return None


def test_direction(manager: CommsManager, out_arm: str, in_arm: str) -> bool:
    """把 out_arm 的輸出開/關，確認 in_arm 讀到的輸入跟著變化"""
    print(f"\n--- 測試方向: {out_arm} 輸出 → {in_arm} 輸入 ---")
    ok = True

    # 先確保 out_arm 輸出是關的，看 in_arm 基準值
    manager.send_command(out_arm, "IOTEST,OFF")
    time.sleep(SETTLE_SEC)
    base = read_sig(manager, in_arm)
    print(f"  基準 (應該是 0): {in_arm} 讀到 = {base}")
    if base != 0:
        print(f"  ✗ 基準值不是 0，可能一開始就有雜訊或接反了")
        ok = False

    # 打開輸出，確認對面讀到 1
    manager.send_command(out_arm, "IOTEST,ON")
    time.sleep(SETTLE_SEC)
    on_val = read_sig(manager, in_arm)
    print(f"  {out_arm} 拉高後: {in_arm} 讀到 = {on_val}")
    if on_val != 1:
        print(f"  ✗ {out_arm} 拉高了，但 {in_arm} 沒讀到 1 —— 這條線沒接通或接錯號碼")
        ok = False
    else:
        print(f"  ✓ {out_arm} → {in_arm} 訊號有接通")

    # 關閉輸出，確認對面讀到 0
    manager.send_command(out_arm, "IOTEST,OFF")
    time.sleep(SETTLE_SEC)
    off_val = read_sig(manager, in_arm)
    print(f"  {out_arm} 拉低後: {in_arm} 讀到 = {off_val}")
    if off_val != 0:
        print(f"  ✗ {out_arm} 拉低了，但 {in_arm} 沒跟著變回 0")
        ok = False

    return ok


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    manager = CommsManager()

    print("正在連線 F60_F 與 F60_R ...")
    if not manager.connect_all():
        print("\n✗ 連線失敗，尚未送出任何指令。")
        print("  請檢查：兩隻手臂電源、網路線、AS 程式是否已在控制器上 EXECUTE。")
        return 1

    print("\n✓ F60_F 與 F60_R 都已連線")
    print("(請確認兩邊控制器上的 AS 程式都已重新上傳、EXECUTE 的是含 IOTEST 指令的最新版)")

    result_fr = test_direction(manager, "F60_F", "F60_R")
    result_rf = test_direction(manager, "F60_R", "F60_F")

    manager.disconnect_all()

    print("\n========== 結果 ==========")
    print(f"F60_F → F60_R: {'✓ 通過' if result_fr else '✗ 失敗'}")
    print(f"F60_R → F60_F: {'✓ 通過' if result_rf else '✗ 失敗'}")

    if result_fr and result_rf:
        print("\n✓ 雙向接線都正常，SYNC_STEP 逾時如果還發生，問題應該不在接線，回頭查程式邏輯或 timeout_io_sec 是否夠長。")
        return 0

    print("\n✗ 至少一個方向沒接通，先處理接線 (腳位、線材、外部 I/O 板設定) 再重跑 FLIP。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
