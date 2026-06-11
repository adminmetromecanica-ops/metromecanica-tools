import serial
import time

s = serial.Serial('COM5', 9600, timeout=3)
print('Enviando comandos...')

comandos = [b'\r\n', b'P\r\n', b'p\r\n', b'\x0D']

for cmd in comandos:
    print(f'Enviando: {cmd}')
    s.write(cmd)
    time.sleep(1)
    if s.in_waiting:
        d = s.read(s.in_waiting)
        print(f'RESPUESTA: {d}')
    else:
        print('Sin respuesta')

s.close()
print('Fin.')