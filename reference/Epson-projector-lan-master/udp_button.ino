#include <Ethernet2.h>
#include <EthernetUdp2.h>
const int buttonPin1 = 7;    // the number of the pushbutton pin

int buttonState1;             // the current reading from the input pin
int lastButtonState1 = LOW;   // the previous reading from the input pin


// the following variables are unsigned longs because the time, measured in
// milliseconds, will quickly become a bigger number than can be stored in an int.
unsigned long lastDebounceTime1 = 0;  // the last time the output pin was toggled
String  ReplyBuffer = "";
unsigned long debounceDelay = 0;    // the debounce time; increase if the output flickers

char incomingData[45];
char *saveptr;
String  ReplyBuffer1 = "";

byte mac[] = { 0x2C, 0xF7, 0xF1, 0x08, 0x31, 0x4E }; //physical mac address

IPAddress localip(192, 168, 1, 111);                      // IP Address (RECIEVER)
IPAddress remoteip(192, 168, 1, 100);               // Remote IP (SERVER)

const unsigned int remotPort = 5001;                // Remote Port
const unsigned int localPort = 8545;                // Local Port
EthernetUDP Udp;


//


const int BUTTON_PIN = 7; // the number of the pushbutton pin
const int relay = 4;

// Variables will change:
int lastState = LOW;
int currentState = LOW;
int x = 0;
int y = 0;
int reading1 = 0;
int remotePin = 6;
int val = 0;

void setup() {
  Serial.begin(9600);
  pinMode(BUTTON_PIN, INPUT_PULLUP);    // the pull-up input pin will be HIGH when the switch is open and LOW when the switch is closed.

  pinMode(relay, OUTPUT);
  pinMode(remotePin, OUTPUT);

  Ethernet.begin(mac, localip);
  Udp.begin(localPort);

}

void loop()
{
  buttonone();
  val = digitalRead(BUTTON_PIN);
  digitalWrite(remotePin, val);
}

void buttonone()
{
  reading1 = digitalRead(buttonPin1);
  if (reading1 != lastButtonState1)
  {
    lastDebounceTime1 = millis();
  }

  if ((millis() - lastDebounceTime1) > debounceDelay)
  {
    if (reading1 != buttonState1)
    {
      buttonState1 = reading1;
      if (buttonState1 == HIGH)
      {
        tete();
        y = 1;
      }
    }
  }
  lastButtonState1 = reading1;
  y = 0;
}

void tete() {
  // read the state of the switch/button:
  currentState = digitalRead(BUTTON_PIN);

  // save the the last state
  lastState = currentState;

  x++;

  if (x % 2 == 0) {
    digitalWrite(relay, LOW);
    Serial.println("POWER ON");
    Udp.beginPacket(remoteip, remotPort);
    ReplyBuffer1 = "Power ON";
    Udp.print(1);
    Udp.endPacket();
    ReplyBuffer1 = "";
    Udp.flush();

  } else {
    digitalWrite(relay, HIGH);
    Serial.println("POWER OFF");
    Udp.beginPacket(remoteip, remotPort);
    ReplyBuffer1 = "Power OFF";
    Udp.print(2);
    Udp.endPacket();
    ReplyBuffer1 = "";
    Udp.flush();
  }
  
}
