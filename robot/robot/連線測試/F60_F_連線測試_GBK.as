; =====================================================================
; SmartCook 連線測試程式 — F60_F (左臂)
; 目的: 只驗證 TCP_LISTEN / TCP_ACCEPT / 握手 / 心跳 / 收發是否正常，
;       不含任何 POINT/TOOL/動作指令。先確認這支能跑通，再換成完整版
;       (F60_F_左臂.as)。
;
; 測試方式:
;   1. 把這支程式當作機器人控制程式執行 (EXECUTE 或 A+RUN)
;   2. PC 端連線後送 "connect\n"，應收到 "BOARD_ID,F60_CTRL_001\n"
;   3. 之後送任何一行文字，會原樣印在教示盒/K-ROSET 螢幕上，並回覆
;      "OK\n"；送 "HEARTBEAT\n" 會回覆 "HEARTBEAT_ACK\n"
;   4. PC 斷線後，程式會自動回到 TCP_ACCEPT 等待下一次連線
; =====================================================================

.PROGRAM INIT_CONST()
  $this_arm = "F60_F"
  port = 9000
  max_length = 255
  tout_accept = 5
  tout_recv = 10
  tout_send = 5
  $rxbuf = ""
.END

.PROGRAM MAIN()
  CALL INIT_CONST
  CALL CLEAN_SOCKET
  CALL OPEN_LISTEN
  DO
    CALL WAIT_ACCEPT(accepted)
    IF accepted == 1 THEN
      sock_open_flag = 1
      $rxbuf = ""
      CALL DO_HANDSHAKE(hs_ok)
      IF hs_ok == 1 THEN
        conn_lost = 0
        DO
          CALL RECV_LINE($line, rok)
          IF rok == 0 THEN
            conn_lost = 1
            PRINT "連線中斷，回到等待"
          ELSE
            PRINT "收到: ", $line
            IF $line == "HEARTBEAT" THEN
              CALL SEND_LINE("HEARTBEAT_ACK")
            ELSE
              CALL SEND_LINE("OK")
            END
          END
        UNTIL conn_lost == 1
      END
      CALL DISCONNECT
    END
  UNTIL 1 == 0
.END

; ---------------------------------------------------------------------
; 斷線處理：統一由這裡呼叫 TCP_CLOSE 並重置 sock_open_flag。
; 正常斷線流程(MAIN 迴圈結尾)與異常殘留清除(CLEAN_SOCKET)都
; 呼叫這支，避免同樣的動作分散在兩個地方各寫一次、以後改一次要改兩處。
; ---------------------------------------------------------------------
.PROGRAM DISCONNECT()
  TCP_CLOSE cret, sock_id
  sock_open_flag = 0
.END

; ---------------------------------------------------------------------
; sock_open_flag 不加 "." 前綴 = 全域變數，控制器不重開機的話，就算
; 程式被中止(HALT/ABORT)重新 EXECUTE，這個值也不會被清掉。
; 用來偵測「上一輪 accept 成功後，還沒跑到斷線處理就被中止」的情況：
; 是的話，這裡先補呼叫 DISCONNECT，關閉上次殘留的連線 socket。
;
; 另外依通訊選項手冊 90210-1344 (1.6.1節 E4055/E4056 說明、1-44頁
; close_socket() 官方範例)：TCP_LISTEN 開的「監聽中」端口，跟
; TCP_ACCEPT 開的「已連線」socket 是兩個獨立資源，各自要用
; TCP_END_LISTEN / TCP_CLOSE 分開釋放。程式被中止時只有連線 socket
; 被 sock_open_flag 追蹤到，監聽中的端口從來沒被釋放過，這才是
; E4055 卡在 TCP_LISTEN 那一步的真正原因。TCP_END_LISTEN 對「本來就
; 沒在監聽」的端口失敗，回傳的是通訊錯誤代碼 E4056(手冊列在同一份
; 通訊錯誤表 1.6.1 節)，屬於「保存錯誤碼、程式繼續執行」的類型，
; 不會像 TCP_CLOSE 對無效 socket 那樣讓程式中止，所以這裡可以無條件
; 呼叫，不需要額外的旗標判斷。
; ---------------------------------------------------------------------
.PROGRAM CLEAN_SOCKET()
  IF sock_open_flag == 1 THEN
    PRINT "偵測到上次殘留的連線 sock_id=", sock_id, "，先關閉再繼續"
    CALL DISCONNECT
  END
  TCP_END_LISTEN eret, port
  IF eret < 0 THEN
    PRINT "TCP_END_LISTEN 啟動清理 回傳=", eret, "（本來就沒有殘留監聽，正常現象）"
  ELSE
    PRINT "TCP_END_LISTEN 啟動清理 成功，已釋放上次殘留的監聽狀態"
  END
.END

.PROGRAM OPEN_LISTEN()
  er_count = 0
listen:
  TCP_LISTEN lret, port
  IF lret < 0 THEN
    er_count = er_count + 1
    PRINT "TCP_LISTEN error=", lret, " count=", er_count
    GOTO listen
  END
  PRINT "TCP_LISTEN OK port=", port
.END

.PROGRAM WAIT_ACCEPT(.accepted)
  TCP_ACCEPT sock_id, port, tout_accept, client_ip[1]
  IF sock_id < 0 THEN
    .accepted = 0
  ELSE
    PRINT "TCP_ACCEPT OK id=", sock_id
    .accepted = 1
  END
.END

; ---------------------------------------------------------------------
; 握手: 收到 "connect" 後回覆 "BOARD_ID,F60_CTRL_001"
; ---------------------------------------------------------------------
.PROGRAM DO_HANDSHAKE(.ok)
  CALL RECV_LINE($line, rok)
  IF rok == 0 THEN
    .ok = 0
    RETURN
  END
  IF $line == "connect" THEN
    CALL SEND_LINE("BOARD_ID,F60_CTRL_001")
    .ok = 1
  ELSE
    CALL SEND_LINE("ERROR,E4021")
    .ok = 0
  END
.END

; ---------------------------------------------------------------------
; 讀取一行 (以 \n 結尾)。.rok=0 代表連線中斷/逾時。
; ---------------------------------------------------------------------
.PROGRAM RECV_LINE(.$line, .rok)
  DO
    nl_pos = INSTR(1, $rxbuf, $CHR(10))
    IF nl_pos > 0 THEN
      .$line = $LEFT($rxbuf, nl_pos - 1)
      $rxbuf = $MID($rxbuf, nl_pos + 1, LEN($rxbuf) - nl_pos)
      .rok = 1
      RETURN
    END
    TCP_RECV rret, sock_id, $recv_buf[1], recv_n, tout_recv, max_length
    IF rret < 0 THEN
      IF rret <> -34024 THEN   ; -34024 = E4024 通信逾時，只是暫時沒新資料，不是斷線
        .rok = 0
        RETURN
      END
    ELSE
      IF recv_n > 0 THEN
        FOR i = 1 TO recv_n
          $rxbuf = $rxbuf + $recv_buf[i]
        END
      END
    END
  UNTIL 1 == 0
.END

; ---------------------------------------------------------------------
; 送出一行 (自動加上 \n)
; ---------------------------------------------------------------------
.PROGRAM SEND_LINE(.$msg)
  $send_buf[1] = .$msg + $CHR(10)
  TCP_SEND sret, sock_id, $send_buf[1], 1, tout_send
.END
