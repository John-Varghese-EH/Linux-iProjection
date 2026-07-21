from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

import socket
import pyautogui, sys
print('Press Ctrl-C to quit.')


driver = webdriver.Firefox()

driver.get("http://192.168.0.103/cgi-bin/Remote/Basic_Control")

time.sleep(5)

accordion = driver.find_element_by_class_name('avmute')

UDP_IP = "192.168.1.100"
UDP_PORT = 5001

sock = socket.socket(socket.AF_INET, # Internet
                     socket.SOCK_DGRAM) # UDP
sock.bind((UDP_IP, UDP_PORT))

while True:
    data, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
    print (data.decode())

    if data.decode() == '1' :
        print("ON")
        accordion.click()
    elif data.decode() == '2':
        print("OFF")
        accordion.click()


accordion.click()
