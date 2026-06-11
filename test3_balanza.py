import serial
import time

baudrates = [1200, 2400, 4800, 9600, 19200, 38400]

for baud in baudrates:
    print(f'\nProbando baudrate: {baud}')
    try:
        s = serial.Serial('COM5', baud, timeout=2)
        time.sleep(0.5)
        if s.in_waiting:
            d = s.read(s.in_waiting)
            print(f'✓ DATOS RECIBIDOS: {d}')
        else:
            # Intentar solicitar dato
            s.write(b'P\r\n')
            time.sleep(1)
            if s.in_waiting:
                d = s.read(s.in_waiting)
                print(f'✓ RESPUESTA: {d}')
            else:
                print('Sin respuesta')
        s.close()
    except Exception as e:
        print(f'Error: {e}')

print('\nFin.')