import serial
import time

s = serial.Serial('COM5', 9600, timeout=3)
print('Esperando datos... (pon un peso en la balanza)')
for i in range(30):
    if s.in_waiting:
        d = s.read(s.in_waiting)
        print('RAW bytes:', d)
    time.sleep(0.5)
s.close()
print('Fin.')