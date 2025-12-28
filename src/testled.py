import time
import blinkt

DELAY = 0.3
BRIGHTNESS = 0.2
PIXELS = 8

blinkt.set_brightness(BRIGHTNESS)
blinkt.clear()
blinkt.show()

def cycle_color(r, g, b, name):
    print(f"{name}: cycling LEDs")
    for i in range(PIXELS):
        blinkt.clear()
        blinkt.set_pixel(i, r, g, b)
        blinkt.show()
        time.sleep(DELAY)
    blinkt.clear()
    blinkt.show()
    time.sleep(DELAY)

cycle_color(255, 0, 0, "Red")
cycle_color(0, 255, 0, "Green")
cycle_color(0, 0, 255, "Blue")

print("Red on for 1s")
for i in range(8):
    blinkt.set_pixel(i, 255, 0, 0)
blinkt.show()
time.sleep(1)

print("Green on for 1s")
blinkt.clear()
for i in range(8):
    blinkt.set_pixel(i, 0, 255, 0)
blinkt.show()
time.sleep(1)

print("Blue on for 2s")
blinkt.clear()
for i in range(8):
    blinkt.set_pixel(i, 0, 0, 255)
blinkt.show()
time.sleep(1)

print("Done")

