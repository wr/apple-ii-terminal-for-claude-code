-- Token device-pairing test for the 8-bit client (Phase 4).
--
-- Boots claude2 under MAME with an SSC wired to a listening bridge, drives
-- the first-run pairing code, then asserts the bridge's CMD_TOKEN frame was
-- captured and framed into the reserved sector buffer TOKBUF ($9000) in the
-- on-disk layout: magic "CLDTK1" | len | token | checksum.
--
-- Harness (mirrors tests/README.md; ROMs live in ~/.mame/roms):
--   cd bridge && python3 bridge.py --telnet --port 6502 --app --backend chat \
--        --cols 80 --pair-code ABCDEF &
--   SDL_VIDEODRIVER=dummy TOKCODE=ABCDEF mame apple2ee -rompath ~/.mame/roms \
--        -aux "" -sl2 ssc -sl2:ssc:rs232 null_modem \
--        -bitbanger socket.127.0.0.1:6502 -flop1 apple2gs/CLAUDE.dsk \
--        -autoboot_script apple2gs/tests/token_pair.lua \
--        -video none -sound none -nothrottle -seconds_to_run 200
--
-- The bridge must be started with a KNOWN --pair-code so the script can type
-- it; pass the same value in TOKCODE (default "ABCDEF"). Prints TOKENTEST:
-- lines; success ends with "ALL PASS".

local mac = manager.machine
local kbd = mac.natkeyboard
local mem = mac.devices[":maincpu"].spaces["program"]

local TOKBUF = 0x9000
local CODE = os.getenv("TOKCODE") or "ABCDEF"

local function screen_text()
  -- decode text page 1 ($0400-$07F7), high bit masked (40-col main RAM)
  local lo = {0x00,0x80,0x00,0x80,0x00,0x80,0x00,0x80,
              0x28,0xA8,0x28,0xA8,0x28,0xA8,0x28,0xA8,
              0x50,0xD0,0x50,0xD0,0x50,0xD0,0x50,0xD0}
  local hi = {0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07,
              0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07,
              0x04,0x04,0x05,0x05,0x06,0x06,0x07,0x07}
  local rows = {}
  for r = 0, 23 do
    local base = hi[r+1]*256 + lo[r+1]
    local s = {}
    for c = 0, 39 do
      local b = mem:read_u8(base + c) & 0x7F
      if b < 0x20 then b = b + 0x40 end
      s[#s+1] = string.char(b)
    end
    rows[#rows+1] = table.concat(s)
  end
  return table.concat(rows, "\n")
end

local function on_menu()
  return screen_text():upper():find("1. CONNECT", 1, true) ~= nil
end

-- read the framed token sector back out of the client's RAM buffer
local function magic_present()
  local s = ""
  for i = 0, 5 do s = s .. string.char(mem:read_u8(TOKBUF + i)) end
  return s == "CLDTK1"
end

local function token_ok()
  -- validate the same layout the client wrote: magic | len | token | csum,
  -- checksum = 8-bit sum of bytes [0 .. 6+len]
  if not magic_present() then return false, "magic missing" end
  local len = mem:read_u8(TOKBUF + 6)
  if len < 1 or len > 40 then return false, "bad len " .. len end
  local sum = 0
  for i = 0, 6 do sum = (sum + mem:read_u8(TOKBUF + i)) & 0xFF end
  for i = 0, len - 1 do sum = (sum + mem:read_u8(TOKBUF + 7 + i)) & 0xFF end
  local stored = mem:read_u8(TOKBUF + 7 + len)
  if sum ~= stored then return false, "checksum " .. sum .. " != " .. stored end
  return true, "len=" .. len
end

local frame = 0
local step = 1
local deadline = 60 * 180
local fails = 0
local function say(s) print("TOKENTEST: " .. s) end

emu.register_frame_done(function()
  frame = frame + 1
  if frame > deadline then say("FAIL timeout in step " .. step); mac:exit(); return end

  if step == 1 then
    if frame % 30 == 0 and on_menu() then
      say("menu up; Connecting")
      kbd:post("1")                     -- Connect: dials, then session/LOCKED
      step = 2; frame = 0
    end
  elseif step == 2 then
    -- let the dial theater (~4s) finish and the LOCKED prompt land, then
    -- type the pairing code; the bridge answers with the CMD_TOKEN frame.
    if frame == 60 * 14 then
      say("typing pairing code " .. CODE)
      kbd:post(CODE .. "\n")
      step = 3; frame = 0
    end
  elseif step == 3 then
    -- give the frame + RWTS write time to land in TOKBUF
    if frame == 60 * 4 then
      local ok, why = token_ok()
      if ok then
        say("PASS token captured and framed (" .. why .. ")")
      else
        say("FAIL token not framed in TOKBUF: " .. why); fails = fails + 1
      end
      say(fails == 0 and "ALL PASS" or ("DONE with " .. fails .. " failures"))
      mac:exit()
    end
  end
end)
