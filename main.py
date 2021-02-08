import os
import time
import math
from subprocess import Popen, PIPE
from queue import Queue, Empty
from threading import Thread
from Button_pad import Button_pad
from resources import RPi_I2C_driver
from datetime import datetime
from Py_to_pd import Py_to_pd

#Globals
COLORS = ["red", "green", "blue", "yellow", "purple", "cyan", "white", "off"]
LOOP_BUTTONS = [1,2,3,4,5,6,7,8]
DRUMPAD_BUTTONS = [9,10,11,12,13,14,15,16]
BLOCK = chr(255) #block to display on screen for metronome
BLANK = chr(32) #blank block to display for metronome
SCREEN_SIZE = 16 #screen size of the LCD display (length)
#PD_PATH = "/Applications/Pd-0.51-1.app/Contents/Resources/bin/" #mac
PD_PATH = "" #pi
PORT_SEND_TO_PD = 3000 #port to communicate message TO PD
PORT_RECEIVE_FROM_PD = 4000 #port to receive messages FROM PD
DIR = '/home/pi/piloopdrumbox' #where does the GIT repo live on the Pi

def read_pd_input(proc, q):
    """
    callback function
    Thread process to read PureData input
    Requires the queue, that stores the socket output
    """
    while True:
        pd_input = proc.readline()
        q.put(pd_input)
        time.sleep(1/10)

def process_pd_input(q):
    """
    callback function
    Constantly read the queue for new messages from PD
    """
    while True:
        try:
            #reads the queue without blocking
            pd_input = q.get().decode()
            if pd_input:
                handle_pd_msg(pd_input)
        except Empty:
            time.sleep(1/10)
            pass

def handle_pd_msg(msg):
    """
    Handle a msg from puredata, which is split by | characters
    """
    x = msg.split("|")
    del x[-1] #remove last element of the list (PD automatically adds \n)
    if x[0] == "counter":
        if not buttons.options_open:
            set_metronome(int(x[1]), int(x[2]))
    if x[0] == "status":
        handle_status(x[1], x[2:])

def handle_status(action, payload):
    """
    Handle status messages from PD
    """
    payload = [int(i) for i in payload]
    action_handler = {
        "clear_rec"     : action_button_color(payload, COLORS[7]), #off
        "start_rec"     : record(action, payload, COLORS[0]), #red
        "start_overdub" : record(action, payload, COLORS[0]), #red
        "stop_rec"      : finish_record(action, payload, COLORS[1]), #green
        "stop_overdub"  : finish_record(action, payload, COLORS[1]), #green
        "wait_rec"      : action_button_color(payload, COLORS[6]), #orange
        "mute_rec"      : mute_record(payload, COLORS[2], COLORS[1]) #blue/green
        }
    try:
        action_handler[action]
    except:
        #not recognized action from PD
        print("unknown action received")

def action_button_color(payload, color):
    buttons.set_button_color(payload[0], color) #off

def record(action, payload, color):
    buttons.set_button_color(payload[0], color) #red
    lcd.lcd_display_string("Start {}: ".format("rec" if action == "start_rec" else "odub") + str(payload[0]), 1)

def finish_record(action, payload, color):
    buttons.set_button_color(payload[0], color) #green
    lcd.lcd_display_string("Finished {}: ".format("rec" if action == "stop_rec" else "odub") + str(payload[0]), 1)

def mute_record(payload, mute_color, unmute_color):
    if payload[0] == 1: #mute
        buttons.set_button_color(payload[1], mute_color) #blue
    if payload[0] == 0: #unmute
        buttons.set_button_color(payload[1], unmute_color) #green

def set_metronome(value, total_beats):
    block_size = math.floor(SCREEN_SIZE / max(total_beats, 4) * (value + 1))
    lcd.lcd_display_string(block_size * BLOCK + (SCREEN_SIZE - block_size) * BLANK, 2)

def read_button_status():
    """
    Thread function that continuously reads the button_pad input
    """
    while True:
        for column in range(4):
            for row in range(4):
                if buttons.button_was_pressed[column][row]:
                    handle_button_press(column, row)
                    # Turn back button press to false
                    buttons.button_was_pressed[column][row] = False
                if buttons.button_was_released[column][row]:
                    handle_button_release(column, row)
                    # Turn back button press to false
                    buttons.button_was_released[column][row] = False
        time.sleep(1/2000)

def handle_button_press(column, row):
    """
    This function handles the button press, not the release
    There's a lot of sintax regarding the
    """
    #Send button press
    if buttons.options_open:
        # Handle options
        button_num = 1 + 4 * column + row
        update_option_lcd()
        if not button_num in [14, 15, 16]:
            # Unknown options button
            lcd.lcd_display_string("Use but 14/15/16", 1)
        if button_num == 14:
            # next option
            buttons.option_number = 0 if buttons.option_number == (len(buttons.options)-1) else buttons.option_number + 1
            update_option_lcd()
        if button_num == 15:
            # apply option
            if buttons.option_number == 0:
                # select_kit
                buttons.option_values[buttons.option_number] = 1 if buttons.option_values[buttons.option_number] == buttons.total_drumkits else buttons.option_values[buttons.option_number] + 1
                send_msg.select_kit(buttons.option_values[buttons.option_number])
            if buttons.option_number == 1:
                # toggle_sound
                buttons.option_values[buttons.option_number] = not buttons.option_values[buttons.option_number]
                if buttons.option_values[buttons.option_number]:
                    send_msg.audio_on()
                else:
                    send_msg.audio_off()
            if buttons.option_number == 2:
                # clear_all
                send_msg.clear_all()
                buttons.option_values[buttons.option_number] = 1
                buttons.active_loops = {1:False, 2:False, 3:False, 4:False, 5:False, 6:False, 7:False, 8:False}
                buttons.init_loop = True
            update_option_lcd()
        if button_num == 16:
            # quit options
            toggle_options()
    else:
        buttons.button_press_time[column][row] = datetime.now()
        button_num = 1 + 4 * column + row
        if button_num > 8 or not buttons.active_loops[button_num]:
            # Press the button if drumkit or no active loop
            # For active loops: wait for release timer (overdub or (un)mute)
            send_msg.press_button(button_num)
        if not buttons.init_loop and button_num <= 8 and (buttons.button_press_time[column][row] - buttons.button_prev_press_time[column][row]).total_seconds() < 0.2:
            # clear when: not initial loop, pressed a loop button, and pressed twice within 1 sec.
            send_msg.clear_loop(button_num)
            buttons.active_loops[button_num] = False
        # Set previous button press time
        buttons.button_prev_press_time[column][row] = buttons.button_press_time[column][row]

def toggle_options():
    """
    Function that toggles the option menu
    """
    buttons.options_open = not buttons.options_open
    if buttons.options_open:
        lcd.lcd_display_string("Options", 1)
        update_option_lcd()
    else:
        lcd.lcd_clear()
        buttons.options_open = False
        buttons.option_number = 0
        buttons.option_values[2] = 0
        lcd.lcd_display_string("Ready to play!", 1)

def update_option_lcd():
    """
    Update the lcd with the selected option
    """
    current_option = buttons.options[buttons.option_number]
    lcd.lcd_display_string(current_option + ":" + str(int(buttons.option_values[buttons.option_number])), 2)

def handle_button_release(column, row):
    """
    Function that handles when a button is released (up)
    - Checks if the button is actually pressed
    - Checks if the button is an active loop, and monitors the time of the
    button press
    - Checks if the pressed button = 13, if long press: open options
    - Lastly: reset the button timer and press time
    """
    #Send key release
    button_num = 1 + 4 * column + row
    button_timer = datetime.now() - buttons.button_press_time[column][row]
    prev_button_timer = datetime.now() - buttons.button_prev_press_time[column][row]
    if button_num < 9:
        # loop button
        if buttons.active_loops[button_num]:
            #active loop: release longer than 1 second: overdub loop, else press_button
            if button_timer.total_seconds() >= 0.2:
                #send overdub loop if row 1 or 2
                send_msg.overdub(button_num)
            else:
                #press button only if not pressed twice within 0.5 second
                send_msg.press_button(button_num)
        if not buttons.init_loop:
            #turn into an active loop if this is not the first press of the initial loop
            #in that case; you don't want to wait until release for mute.
            buttons.active_loops[button_num] = True
        else:
            #Set the initial loop to false; initial loop is now recorded
            buttons.init_loop = False
    if button_timer.seconds >= 0.5 and button_num == 13:
        #open the option menu
        toggle_options()

# Set up the LCD
lcd = RPi_I2C_driver.lcd()
lcd.lcd_display_string("Loading...", 1)
lcd.lcd_display_string("Version 1.2", 2)

# Set up communication to PureData
send_msg = Py_to_pd(PD_PATH, PORT_SEND_TO_PD)

# Set up the GPIO library and Pins
buttons = Button_pad()
buttons.setup_buttons() #Initialize the Pins of leds/buttons
for drumpad_button in DRUMPAD_BUTTONS:
    #Set buttons to white color
    buttons.set_button_color(drumpad_button, COLORS[5])

# start the socket
args = ["pdreceive", str(PORT_RECEIVE_FROM_PD)]
process_socket_PD = Popen(args, stdout=PIPE) #second process to read PD
proc_q = Queue() #queue for messages from PD
# Seperate threads for reading/handling the output from PD
read_pd_thread = Thread(target = read_pd_input, args = (process_socket_PD.stdout, proc_q))
process_pd_thread = Thread(target = process_pd_input, args = (proc_q, ))
# Thread to handle the button press/release
handle_button_press_release = Thread(target = read_button_status, args = ())

read_pd_thread.start()
process_pd_thread.start()
handle_button_press_release.start()

# start PD
os.system(PD_PATH + 'pd -nogui main.pd &')
time.sleep(2)

lcd.lcd_display_string("Ready to play!", 1)

while True:
    # Run button loop
    buttons.scan()
    time.sleep(1/1000)
