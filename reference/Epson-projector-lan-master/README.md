# EPSON projector control

The EPSON projector has a web remote that can be used to control the projector. The issue is I still have to go to the browser and click on the buttons. So I have automated the process using selenium.

The code was written such that I could press a button placed on the couch and the projector would mute/unmute the display, and the button was connected to an Arduino which sends signals to my main PC running the code. 

## Installation

Download and Install python3. Add python to the path. 

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install Selenium.

```bash
pip install selenium
```
You also need to get the webdriver depending on which browser you want to use. I used firefox so I had to get the geckodriver and paste it in my root.






# PC and Projector Setup

### Setup - PC

Change network settings of PC:

- Set the IP to any of your choices but make sure it has the same subnet masking as the projector


### Setup - Projector

1. Make sure that you have DHCP turned off. 

2. Check the IP and note it down. 

3. Remove security password.


### Usage
```python
driver.get("http://192.168.0.103/cgi-bin/Remote/Basic_Control")
```
This is the default IP of the EPSON projector. Set it to whatever your NEC is set to that you found in step 2 above.

```python
accordion = driver.find_element_by_class_name('avmute')
```
Change the element from 'avmute' to any other element of your choosing. You can do an inspect element of the page to get the name of the button that you want to press.

# Arduino Setup
There is a button which when pressed the Arduino sends a value over serial. It's a boolean value, so it can either be 0 or 1. 

Pushbuttons often generate spurious open/close transitions when pressed, due to mechanical and physical issues: these transitions may be read as multiple presses in a very short time fooling the program. Hence a debounce was used which limits readings from the button over the short time. 

In the code I've uploaded it has been kept as 0, and you should set it up as it best fits your button/code limitations. 

I also had a relay for my mood lighting setup which also turns on when the button is pressed.
### Wiring
- Connect the button to pin 7 and the other one to ground.
- Connect the relay to pin 4
### Installation 
Install the ethernet2 and ethernet2Udp libraries
```arduino
#include <Ethernet2.h>
#include <EthernetUdp2.h>
```

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
[MIT](https://choosealicense.com/licenses/mit/)
