; =====================================================================
; claude2.s - text-mode client for 8-bit Apples: IIe, IIc, IIc Plus,
; and II/II+ (40-col). Plain 6502 only - no 65C02 ops - so one binary
; runs on everything. The IIgs gets the SHR client (claude.s); if this
; binary finds itself on a GS it says so and exits.
;
; Serial: 6551 ACIA at the slot-2 addresses - which is both an Apple
; Super Serial Card in slot 2 (IIe/II+) and the IIc/IIc+ built-in
; modem port (they're wired at the same soft switches). 9600 8N1.
; RX is interrupt-driven into a page ring buffer (a 1-byte ACIA FIFO
; at 9600 = one char time of slack; scrolling would drop bytes), with
; a polled fallback woven through every slow loop for SSCs whose IRQ
; DIP is off. TX polls TDRE with a timeout (W65C51N never sets it).
;
; Protocol: same app-mode stream as the IIgs client. 0x01 <n> color
; (3 -> inverse, else normal), 0x02 bullet, 0x0E header frame (3 CR
; lines), 0x03 session over, 0x04 EOT.
; =====================================================================

; ---- zero page (safe under Applesoft+DOS: see CLAUDE.md landmines)
ptr     = $06           ; screen row pointer
src     = $08           ; scroll source pointer
tmp     = $FA
tmp2    = $FB
curx    = $FC
cury    = $FD
invflag = $FE           ; 0 normal, nonzero inverse

; ---- hardware
KBD     = $C000
KBDSTRB = $C010
STORE80ON  = $C001      ; write: 80STORE on (PAGE2 banks text page)
STORE80OFF = $C000      ; write
COL80ON    = $C00D      ; write
ALTCHARON  = $C00F      ; write: inverse lowercase, no flash
PAGE2OFF   = $C054      ; any access
PAGE2ON    = $C055
VBLBIT     = $C019      ; bit7 toggles with VBL (IIe/IIc; absent on II+)

ACIA_D  = $C0A8         ; SSC slot 2 == IIc/IIc+ modem port
ACIA_S  = $C0A9
ACIA_CMD = $C0AA
ACIA_CTL = $C0AB

ASAVE   = $45           ; monitor stashes A here before JMP ($3FE)
IRQVEC  = $03FE
DOSWARM = $03D0

RING    = $1F00         ; 256-byte rx ring (page below the program)

; ---- protocol
EOT        = $04
CMD_COLOR  = $01
CMD_BULLET = $02
CMD_QUIT   = $03
CMD_HEADER = $0E

; ---- layout (matches the GS client's shape)
TOPROW  = 6             ; transcript window
BTMROW  = 20
RULE1   = 21
INPUTR  = 22
RULE2   = 23
HDRCOL  = 18            ; header text, right of the mascot

; =====================================================================
; entry: identify the machine, set up screen + serial, menu
; =====================================================================
entry:
        sei
        cld
        lda     #0
        sta     quitflag
        sta     rb_head
        sta     rb_tail
        sta     invflag

        ; ---- machine id (Apple II Misc TN #7)
        lda     $FBB3
        cmp     #$06
        beq     @newer
        ; $38 = Apple ][, $EA = ][+ : 40-col text path
        lda     #0
        sta     has80
        sta     hasvbl
        beq     @setw
@newer: lda     #1
        sta     hasvbl          ; IIe/IIc/IIc+ all have $C019
        lda     $FBC0
        beq     @iic            ; $00 = IIc family (built-in 80 col)
        cmp     #$E0
        bne     @iie            ; $EA = unenhanced IIe
        ; enhanced IIe or IIgs: the GS id hook at $FE1F clears carry
        sec
        jsr     $FE1F
        bcc     gs_bail
@iie:   jsr     aux_test        ; IIe: 80 col only if an aux card is in
        jmp     @setw
@iic:   lda     #1
        sta     has80
@setw:
        lda     has80
        beq     @w40
        lda     #80
        sta     width
        sta     STORE80ON       ; 80STORE stays on for the whole run
        sta     COL80ON
        sta     ALTCHARON
        lda     #$7F            ; inverse mask incl. lowercase
        sta     invmask
        jmp     @serial
@w40:   lda     #40
        sta     width
        lda     #$3F            ; II+ inverse: uppercase/symbols only
        sta     invmask

@serial:
        ; ---- 6551: 9600 8N1, DTR on, polled (no interrupts).
        ; IRQ-driven rx died in practice: the enhanced IIe/IIc ROM
        ; interrupt dispatcher doesn't use the II+'s "A saved at $45"
        ; protocol, and a handler that assumes it corrupts the ROM's
        ; banking restore (symptom: 80STORE drops, even columns
        ; garble, eventually a crash-reboot). Polling is universal:
        ; every loop in this client calls rb_poll at least every
        ; ~600 cycles, and the byte budget at 9600 is ~1000.
        lda     #$1E
        sta     ACIA_CTL
        lda     #$0B            ; DTR on, RX IRQ disabled, RTS low
        sta     ACIA_CMD
        lda     ACIA_D          ; flush any pending byte
        cli
        jmp     menu_screen

; the GS boots this disk into the SHR client via HELLO; landing here
; means someone BRUNs COBJ8 on a GS by hand
gs_bail:
        cli
        ldx     #0
@l:     lda     str_gs,x
        beq     @done
        ora     #$80
        jsr     $FDED           ; COUT
        inx
        bne     @l
@done:  jmp     DOSWARM

; aux_test - IIe: is there memory behind the 80STORE window?
aux_test:
        sta     STORE80ON
        bit     PAGE2ON
        lda     #$42
        sta     $0400
        bit     PAGE2OFF
        lda     #$24
        sta     $0400
        bit     PAGE2ON
        lda     $0400
        cmp     #$42
        bit     PAGE2OFF
        beq     @has
        sta     STORE80OFF
        lda     #0
        sta     has80
        rts
@has:   lda     #1
        sta     has80
        rts

; rb_poll - move a waiting rx byte into the ring. THE serial read
; path: call from inside anything slow (the 6551 buffers ONE byte).
rb_poll:
        txa
        pha
        lda     ACIA_S
        and     #$08
        beq     @out
        lda     ACIA_D
        ldx     rb_head
        sta     RING,x
        inx
        stx     rb_head         ; page ring: index wraps by itself
@out:   pla
        tax
        rts

havebyte:
        jsr     rb_poll
        lda     rb_head
        cmp     rb_tail
        rts                     ; Z clear = byte waiting

getbyte:
        jsr     havebyte
        beq     getbyte
        ldx     rb_tail
        lda     RING,x
        inx
        stx     rb_tail
        rts

; aciaput - send A. Polls TDRE, but gives up after ~3ms so a W65C51N
; (TDRE never sets) still transmits at full rate.
aciaput:
        sta     tmp
        txa
        pha
        ldx     #0
@w:     lda     ACIA_S
        and     #$10
        bne     @go
        inx
        bne     @w
@go:    pla
        tax
        lda     tmp
        sta     ACIA_D
        rts

; =====================================================================
; screen primitives - direct text page writes, main/aux interleave
; =====================================================================

; putscr - A = screen code, draw at (curx,cury), advance curx
putscr:
        pha
        ldx     cury
        lda     rowlo,x
        sta     ptr
        lda     rowhi,x
        sta     ptr+1
        lda     has80
        beq     @m40
        lda     curx
        lsr                     ; y = x/2, carry = odd column
        tay
        pla
        bcs     @odd
        bit     PAGE2ON         ; even column lives in aux ram
        sta     (ptr),y
        bit     PAGE2OFF
        inc     curx
        rts
@odd:   sta     (ptr),y
        inc     curx
        rts
@m40:   ldy     curx
        pla
        sta     (ptr),y
        inc     curx
        rts

; conv - ascii in A -> screen code honoring invflag
conv:
        ldx     invflag
        beq     @n
        and     invmask
        rts
@n:     ora     #$80
        rts

; cout - print ascii A at the transcript cursor; CR = newline; wraps
; and scrolls the TOPROW..BTMROW window
cout:
        cmp     #$0D
        beq     @nl
        cmp     #$20
        bcc     @ret            ; other control chars: ignore
        cmp     #$7F
        bcs     @ret
        jsr     conv
        jsr     putscr
        lda     curx
        cmp     width
        bcc     @ret
@nl:    lda     #0
        sta     curx
        inc     cury
        lda     cury
        cmp     #BTMROW+1
        bcc     @ret
        lda     #BTMROW
        sta     cury
        jsr     scroll_win
@ret:   rts

; scroll_win - scroll TOPROW..BTMROW up one line. rb_poll between
; every 40-byte pass: at 9600 a byte lands every ~1000 cycles.
scroll_win:
        ldx     #TOPROW
@row:   lda     rowlo,x
        sta     ptr
        lda     rowhi,x
        sta     ptr+1
        lda     rowlo+1,x
        sta     src
        lda     rowhi+1,x
        sta     src+1
        jsr     rb_poll
        lda     has80
        beq     @main
        bit     PAGE2ON
        ldy     #39
@a:     lda     (src),y
        sta     (ptr),y
        dey
        bpl     @a
        bit     PAGE2OFF
        jsr     rb_poll
@main:  ldy     #39
@b:     lda     (src),y
        sta     (ptr),y
        dey
        bpl     @b
        jsr     rb_poll
        inx
        cpx     #BTMROW
        bne     @row
        lda     #BTMROW
        ; fall through: clear row A

; clear_rowA - fill row A with normal spaces (both banks in 80 col)
clear_rowA:
        tax
        lda     rowlo,x
        sta     ptr
        lda     rowhi,x
        sta     ptr+1
        jsr     rb_poll
        lda     has80
        beq     @m
        bit     PAGE2ON
        ldy     #39
        lda     #$A0
@ca:    sta     (ptr),y
        dey
        bpl     @ca
        bit     PAGE2OFF
@m:     ldy     #39
        lda     #$A0
@cm:    sta     (ptr),y
        dey
        bpl     @cm
        rts

clear_screen:
        lda     #23
@l:     pha
        jsr     clear_rowA
        pla
        sec
        sbc     #1
        bpl     @l
        rts

; draw_at - X=col, A=row, then print the 0-terminated string at strp
draw_at:
        sta     cury
        stx     curx
draw_str:
        ldy     #0
@l:     lda     (src),y         ; src doubles as the string pointer here
        beq     @d
        ldx     curx            ; clip at the right edge (40-col pages)
        cpx     width
        bcs     @d
        jsr     conv
        sty     tmp2
        jsr     putscr
        ldy     tmp2
        iny
        bne     @l
@d:     rts

; setstr macro-ish helper: A/X = lo/hi of string -> src
.macro  STR  s, col, row
        lda     #<s
        sta     src
        lda     #>s
        sta     src+1
        ldx     #col
        lda     #row
        jsr     draw_at
.endmacro

; =====================================================================
; timing - one display frame, machine-aware, always bounded
; =====================================================================
frame_wait:
        txa                     ; callers count frames in X/Y - keep them
        pha
        tya
        pha
        jsr     fw_core
        pla
        tay
        pla
        tax
        rts
fw_core:
        lda     hasvbl
        beq     @plus           ; II/II+: calibrated ~16ms loop
        lda     VBLBIT
        and     #$80
        sta     tmp
        ldx     #0
        ldy     #120
@w1:    lda     VBLBIT          ; wait for the bit to flip...
        and     #$80
        cmp     tmp
        bne     @ph2
        inx
        bne     @w1
        dey
        bne     @w1
        rts                     ; bounded: bit never moved (weird clone)
@ph2:   sta     tmp
        ldx     #0
        ldy     #120
@w2:    lda     VBLBIT          ; ...and flip back = exactly one frame,
        and     #$80            ; whichever polarity this machine uses
        cmp     tmp
        bne     @out
        inx
        bne     @w2
        dey
        bne     @w2
@out:   rts
@plus:  ldy     #13
@d1:    ldx     #0
@d2:    jsr     rb_poll         ; ~16ms of delay that stays deaf-proof
        inx
        bne     @d2
        dey
        bne     @d1
        rts

; =====================================================================
; mascot - the critter in inverse blocks, 16 wide x 5 tall
; =====================================================================
; A = top row, X = left column
draw_mascot:
        sta     tmp             ; row
        stx     mcol
        lda     #0
        sta     tmp2            ; art row index
@row:   jsr     rb_poll
        lda     tmp
        sta     cury
        lda     mcol
        sta     curx
        lda     tmp2
        asl
        asl
        asl
        asl                     ; *16
        tax
        ldy     #16
@cell:  lda     mascot_art,x
        cmp     #'X'
        beq     @blk
        lda     #$A0            ; background: normal space
        bne     @put
@blk:   lda     #$20            ; inverse space = solid block
@put:   stx     tmp3
        sty     tmp4
        jsr     putscr
        ldy     tmp4
        ldx     tmp3
        inx
        dey
        bne     @cell
        inc     tmp
        inc     tmp2
        lda     tmp2
        cmp     #5
        bne     @row
        rts

mascot_art:
        .byte   "  XXXXXXXXXXXX  "
        .byte   "  XX XXXXXX XX  "
        .byte   "XXXXXXXXXXXXXXXX"
        .byte   "  XXXXXXXXXXXX  "
        .byte   "   X X    X X   "

; =====================================================================
; boot menu
; =====================================================================
menu_screen:
        jsr     clear_screen
        lda     #0
        sta     menusel
        lda     width           ; center the mascot: (width-16)/2
        sec
        sbc     #16
        lsr
        tax
        lda     #2
        jsr     draw_mascot
        ; title, centered
        lda     width
        sec
        sbc     #37
        lsr
        tax
        lda     #<str_title
        sta     src
        lda     #>str_title
        sta     src+1
        lda     #9
        jsr     draw_at
        STR     str_by, 2, 23
menu_loop:
        jsr     menu_draw
@key:   jsr     rb_poll
        lda     KBD
        bpl     @key
        sta     KBDSTRB
        and     #$7F
        cmp     #$0B            ; up
        beq     @up
        cmp     #$0A            ; down
        beq     @dn
        cmp     #$0D
        beq     @go
        cmp     #'1'
        bcc     @key
        cmp     #'5'
        bcs     @key
        sec
        sbc     #'1'
        sta     menusel
        jmp     @go
@up:    lda     menusel
        beq     @key
        dec     menusel
        jmp     menu_loop
@dn:    lda     menusel
        cmp     #3
        bcs     @key
        inc     menusel
        jmp     menu_loop
@go:    lda     menusel
        beq     act_connect
        cmp     #1
        beq     @modem
        cmp     #2
        beq     @instr
        jmp     act_quit
@modem: jmp     page_modem
@instr: jmp     page_instr

menu_draw:
        ldx     #0
@item:  txa
        pha
        cpx     menusel
        beq     @sel
        lda     #0
        sta     invflag
        beq     @draw
@sel:   lda     #1
        sta     invflag
@draw:  txa
        asl
        tay
        lda     menu_ptrs,y
        sta     src
        lda     menu_ptrs+1,y
        sta     src+1
        lda     width
        sec
        sbc     #16
        lsr
        tax
        pla
        pha
        clc
        adc     #12             ; items at rows 12-15
        jsr     draw_at
        lda     #0
        sta     invflag
        pla
        tax
        inx
        cpx     #4
        bne     @item
        rts

act_quit:
        lda     #$02            ; command reg: DTR off, RX IRQ disabled
        sta     ACIA_CMD
        jsr     clear_screen    ; clear while 80STORE is still wired up
        lda     has80
        beq     @t
        sta     $C00C           ; back to 40-col for the BASIC prompt
        sta     STORE80OFF
        bit     PAGE2OFF
@t:     jmp     DOSWARM

; =====================================================================
; connect - junk-flush, dial, classify the modem's verdict (W-477)
; =====================================================================
act_connect:
        lda     #RULE1
        jsr     clear_rowA
        lda     #INPUTR
        jsr     clear_rowA
        STR     str_dial, 2, INPUTR
        lda     #0
        sta     dialres
        sta     mdm_c1
        lda     #$0D            ; flush any half-typed junk on the modem
        jsr     aciaput
        ldx     #15             ; ~250ms, then drop the response
@fl:    jsr     frame_wait
        dex
        bne     @fl
        lda     rb_head
        sta     rb_tail
        ldx     #0
@dial:  lda     str_atd,x
        beq     @cr
        jsr     aciaput
        inx
        bne     @dial
@cr:    lda     #$0D
        jsr     aciaput
        ldx     #45             ; ~3s dial window at 15 frames/beat... 45*4
@beat:  txa
        pha
        ldy     #4
@fw:    jsr     frame_wait
        dey
        bne     @fw
@rx:    jsr     havebyte
        beq     @ck
        jsr     getbyte
        jsr     dial_byte
        jmp     @rx
@ck:    pla
        tax
        lda     dialres
        cmp     #1
        beq     @sess           ; CONNECT
        cmp     #2
        beq     @fail           ; ERROR/BUSY/NO x
        dex
        bne     @beat
@sess:  jmp     session_start   ; silence after 3s = emulator/already online
@fail:  lda     #INPUTR
        jsr     clear_rowA
        STR     str_dfail, 2, INPUTR
        ldx     #180            ; ~3s, back to the menu
@fx:    jsr     frame_wait
        dex
        bne     @fx
        jmp     menu_screen

; dial_byte - first-letter line classifier: E/B = fail, NO.. = fail,
; CO.. = connect. Sets dialres 1/2. (Port of the GS routine.)
dial_byte:
        and     #$7F
        cmp     #$0D
        beq     @nl
        cmp     #$20
        bcc     @x
        ldx     mdm_c1
        bne     @c2
        sta     mdm_c1
        cmp     #'E'
        beq     @fail
        cmp     #'B'
        beq     @fail
        rts
@c2:    cpx     #$FF
        beq     @x
        pha
        lda     #$FF
        sta     mdm_c1
        pla
        cmp     #'O'
        bne     @x
        cpx     #'C'
        beq     @conn
        cpx     #'N'
        beq     @fail
        rts
@conn:  lda     #1
        sta     dialres
        rts
@fail:  lda     #2
        sta     dialres
@nl:    lda     #0
        sta     mdm_c1
@x:     rts

; =====================================================================
; session
; =====================================================================
session_start:
        jsr     clear_screen
        lda     #0
        tax
        jsr     draw_mascot     ; header slot: top-left
        lda     #0
        sta     curx
        lda     #TOPROW
        sta     cury
        sta     quitflag
main:
        jsr     draw_box
        jsr     read_line
        lda     linelen
        beq     main
        jsr     draw_box
        jsr     echo_user
        jsr     send_line
        ; /quit honored locally: works with a dead link too
        lda     linelen
        cmp     #5
        bne     @spin
        ldx     #4
@q:     lda     linebuf,x
        ora     #$20
        cmp     str_quit,x
        bne     @spin
        dex
        bpl     @q
        jmp     quit_to_menu
@spin:  jsr     spinner
        jsr     recv_reply
        lda     quitflag
        beq     main
quit_to_menu:
        lda     #0
        sta     quitflag
        lda     rb_head         ; drop the bridge's goodbye bytes
        sta     rb_tail
        jmp     menu_screen

; draw_box preserves the transcript cursor (curx/cury belong to the
; transcript; the input row borrows them and must give them back)
draw_box:
        lda     curx
        pha
        lda     cury
        pha
        lda     #RULE1
        jsr     rule_row
        lda     #RULE2
        jsr     rule_row
        lda     #INPUTR
        jsr     clear_rowA
        lda     #INPUTR
        sta     cury
        lda     #0
        sta     curx
        lda     #'>'
        ora     #$80
        jsr     putscr
        lda     #$A0
        jsr     putscr
        pla
        sta     cury
        pla
        sta     curx
        rts

rule_row:
        sta     cury
        lda     #0
        sta     curx
        ldx     width
@l:     txa
        pha
        jsr     rb_poll
        lda     #'-'
        ora     #$80
        jsr     putscr
        pla
        tax
        dex
        bne     @l
        rts

; echo_user - "> line" into the transcript, inverse (the II's "white")
echo_user:
        lda     #1
        sta     invflag
        lda     #'>'
        jsr     cout
        lda     #' '
        jsr     cout
        ldx     #0
@l:     cpx     linelen
        beq     @d
        lda     linebuf,x
        stx     tmp3
        jsr     cout
        ldx     tmp3
        inx
        bne     @l
@d:     lda     #0
        sta     invflag
        lda     #$0D
        jsr     cout
        jmp     cout_cr_pad     ; blank line after

cout_cr_pad:
        lda     #$0D
        jmp     cout

send_line:
        ldx     #0
@l:     cpx     linelen
        beq     @d
        lda     linebuf,x
        jsr     aciaput
        inx
        bne     @l
@d:     lda     #$0D
        jmp     aciaput

; =====================================================================
; read_line - into linebuf, echo at the input row. Handles the
; bridge's idle traffic (header frames at boot, stray CRs).
; =====================================================================
read_line:
        lda     curx            ; borrow the cursor for the input row;
        sta     tcurx           ; the transcript gets it back at exit
        lda     cury
        sta     tcury
        lda     #2              ; after "> "
        sta     curx
        lda     #INPUTR
        sta     cury
        lda     #0
        sta     linelen
@key:   jsr     rb_poll
        jsr     havebyte
        beq     @kbd
        ldx     rb_tail         ; peek: only consume protocol traffic
        lda     RING,x
        and     #$7F
        cmp     #CMD_HEADER
        beq     @hdr
        cmp     #CMD_QUIT
        beq     @rq
        jsr     getbyte         ; stray byte (CONNECT echo etc): discard
        jmp     @key
@hdr:   jsr     getbyte
        jsr     do_header
        jmp     @key
@rq:    jsr     getbyte
        lda     #1
        sta     quitflag
        lda     #0
        sta     linelen
        beq     @done           ; restore the transcript cursor on this exit too
@kbd:   lda     KBD
        bpl     @key
        sta     KBDSTRB
        and     #$7F
        cmp     #$0D
        beq     @done
        cmp     #$08            ; left arrow = backspace
        beq     @bs
        cmp     #$7F
        beq     @bs
        cmp     #$20
        bcc     @key
        ldx     linelen
        cpx     #120
        bcs     @key
        sta     linebuf,x
        inc     linelen
        ldx     curx            ; echo only while it fits on the row
        cpx     width
        bcs     @key
        ora     #$80
        jsr     putscr
        jmp     @key
@bs:    lda     linelen
        beq     @key
        dec     linelen
        dec     curx
        lda     #$A0
        jsr     putscr
        dec     curx
        jmp     @key
@done:  lda     tcurx
        sta     curx
        lda     tcury
        sta     cury
        rts

; =====================================================================
; spinner - pulse until the reply's first real byte. Esc = bail to
; the menu (dead-link escape hatch).
; =====================================================================
spinner:
        lda     #0
        sta     havefirst
        sta     sp_ph
@lp:    lda     KBD
        bpl     @nk
        sta     KBDSTRB
        and     #$7F
        cmp     #$1B
        bne     @nk
        lda     #1
        sta     quitflag
        lda     #EOT            ; fake end-of-reply
        jmp     @stash
@nk:    jsr     havebyte
        beq     @draw
        jsr     getbyte
        and     #$7F
        cmp     #EOT
        beq     @stash
        cmp     #CMD_COLOR
        beq     @stash
        cmp     #CMD_BULLET
        beq     @stash
        cmp     #CMD_HEADER
        beq     @stash
        cmp     #CMD_QUIT
        beq     @q
        cmp     #$20
        bcc     @lp             ; pre-reply CR/LF: discard
        cmp     #$7F
        bcs     @lp
@stash: sta     firstbyte
        lda     #1
        sta     havefirst
        ; erase the pulse cell
        lda     cury
        pha
        lda     curx
        pha
        lda     #0
        sta     curx
        lda     #BTMROW
        sta     cury
        lda     #$A0
        jsr     putscr
        pla
        sta     curx
        pla
        sta     cury
        rts
@q:     lda     #1
        sta     quitflag
        jmp     @lp
@draw:  lda     cury
        pha
        lda     curx
        pha
        lda     #0
        sta     curx
        lda     #BTMROW
        sta     cury
        inc     sp_ph
        lda     sp_ph
        lsr
        lsr
        and     #$03
        tax
        lda     sp_glyphs,x
        ora     #$80
        jsr     putscr
        pla
        sta     curx
        pla
        sta     cury
        jsr     frame_wait
        jmp     @lp

; =====================================================================
; recv_reply - stream until EOT (mirror of the GS routine)
; =====================================================================
recv_reply:
        lda     #0
        sta     invflag
        sta     colorpend
        lda     havefirst
        beq     @next
        lda     firstbyte
        jmp     @disp
@next:  jsr     getbyte
        and     #$7F
@disp:  ldx     colorpend
        beq     @nocp
        cmp     #3              ; color 3 (white/code) -> inverse
        beq     @inv
        lda     #0
        sta     invflag
        beq     @clr
@inv:   lda     #1
        sta     invflag
@clr:   lda     #0
        sta     colorpend
        beq     @next
@nocp:  cmp     #EOT
        beq     @done
        cmp     #CMD_COLOR
        beq     @setcp
        cmp     #CMD_BULLET
        beq     @bullet
        cmp     #CMD_HEADER
        beq     @hdr
        cmp     #CMD_QUIT
        beq     @rq
        cmp     #$0A
        beq     @next
        jsr     cout
        jmp     @next
@setcp: lda     #1
        sta     colorpend
        bne     @next
@bullet:lda     #'*'
        jsr     cout
        lda     #' '
        jsr     cout
        jmp     @next
@hdr:   jsr     do_header
        jmp     @next
@rq:    lda     #1
        sta     quitflag
        bne     @next
@done:  lda     #$0D
        jsr     cout
        lda     #$0D
        jsr     cout
        lda     #0
        sta     havefirst
        rts

; =====================================================================
; do_header - 3 CR-terminated lines drawn beside the mascot (rows
; 1-3, col HDRCOL). The window scroll never touches them.
; =====================================================================
do_header:
        lda     curx
        pha
        lda     cury
        pha
        lda     #1
        sta     hdr_row
@line:  lda     #HDRCOL
        sta     curx
        lda     hdr_row
        sta     cury
@ch:    jsr     getbyte
        and     #$7F
        cmp     #$0D
        beq     @eol
        cmp     #$20
        bcc     @ch
        ldx     curx
        cpx     width
        bcs     @ch             ; truncate at the right edge
        ora     #$80
        jsr     putscr
        jmp     @ch
@eol:   ; pad the rest of the line (clears a previous longer header)
        ldx     curx
@pad:   cpx     width
        bcs     @nl
        lda     #$A0
        jsr     putscr
        ldx     curx
        jmp     @pad
@nl:    inc     hdr_row
        lda     hdr_row
        cmp     #4
        bne     @line
        pla
        sta     cury
        pla
        sta     curx
        rts

; =====================================================================
; modem console - raw keys out, raw bytes in. Esc = menu.
; =====================================================================
page_modem:
        jsr     clear_screen
        STR     str_mdm_t, 2, 1
        STR     str_mdm_h, 2, 3
        lda     #0
        sta     curx
        lda     #TOPROW
        sta     cury
@lp:    jsr     rb_poll
        jsr     havebyte
        beq     @kbd
        jsr     getbyte
        and     #$7F
        cmp     #$0A
        beq     @lp
        jsr     cout
        jmp     @lp
@kbd:   lda     KBD
        bpl     @lp
        sta     KBDSTRB
        and     #$7F
        cmp     #$1B
        beq     @out
        jsr     aciaput         ; live console: every key straight out
        jmp     @lp
@out:   jmp     menu_screen

; =====================================================================
; instructions
; =====================================================================
page_instr:
        jsr     clear_screen
        STR     str_ins_t, 2, 1
        STR     str_ins_1, 2, 3
        STR     str_ins_2, 2, 5
        STR     str_ins_3, 2, 6
        STR     str_ins_4, 2, 7
        STR     str_ins_5, 2, 9
        STR     str_ins_6, 2, 11
        STR     str_esc, 2, 22
@k:     jsr     rb_poll
        lda     KBD
        bpl     @k
        sta     KBDSTRB
        jmp     menu_screen

; =====================================================================
; strings
; =====================================================================
str_title:  .byte "Claude Code Terminal for the Apple ][",0
str_by:     .byte "by Wells Workshop",0
str_dial:   .byte "Dialing...",0
str_dfail:  .byte "Dial failed - try the modem console",0
str_atd:    .byte "ATDS=0",0
str_quit:   .byte "/quit"
str_gs:     .byte "THIS IS THE 8-BIT CLIENT - ON A IIGS RUN: BRUN COBJ",$0D,0
str_mdm_t:  .byte "Hayes AT console",0
str_mdm_h:  .byte "Keys go straight to the modem. Esc = menu.",0
str_ins_t:  .byte "Instructions",0
str_ins_1:  .byte "Talk to Claude Code from this Apple II, over a WiFi modem.",0
str_ins_2:  .byte "The bridge (on a modern computer):",0
str_ins_3:  .byte " github.com/wr/claude-code-terminal-for-apple-ii",0
str_ins_4:  .byte " python3 bridge.py --telnet --app --backend code",0
str_ins_5:  .byte "Modem: store the bridge as entry 0 (AT&Z0=host:6400, AT&W).",0
str_ins_6:  .byte "Connect on the menu dials ATDS=0 and starts the session.",0
str_esc:    .byte "Any key returns to the menu",0
sp_glyphs:  .byte "*+:+"
menu_ptrs:  .word mi0, mi1, mi2, mi3
mi0:        .byte "1. Connect",0
mi1:        .byte "2. Modem",0
mi2:        .byte "3. Instructions",0
mi3:        .byte "4. Quit to Basic",0

; text page row bases
rowlo:  .byte $00,$80,$00,$80,$00,$80,$00,$80
        .byte $28,$A8,$28,$A8,$28,$A8,$28,$A8
        .byte $50,$D0,$50,$D0,$50,$D0,$50,$D0
rowhi:  .byte $04,$04,$05,$05,$06,$06,$07,$07
        .byte $04,$04,$05,$05,$06,$06,$07,$07
        .byte $04,$04,$05,$05,$06,$06,$07,$07

; =====================================================================
; bss
; =====================================================================
rb_head:    .res 1
rb_tail:    .res 1
has80:      .res 1
hasvbl:     .res 1
width:      .res 1
invmask:    .res 1
quitflag:   .res 1
colorpend:  .res 1
havefirst:  .res 1
firstbyte:  .res 1
linelen:    .res 1
menusel:    .res 1
dialres:    .res 1
mdm_c1:     .res 1
sp_ph:      .res 1
hdr_row:    .res 1
mcol:       .res 1
tmp3:       .res 1
tmp4:       .res 1
tcurx:      .res 1          ; transcript cursor parked during input
tcury:      .res 1
linebuf:    .res 128
