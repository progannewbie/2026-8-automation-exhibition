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
  CALL OPEN_LISTEN
  DO
    CALL WAIT_ACCEPT(accepted)
    IF accepted == 1 THEN
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
      TCP_CLOSE cret, sock_id
    END
  UNTIL 1 == 0
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
