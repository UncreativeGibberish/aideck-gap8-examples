import socket
import struct
import cv2
import numpy as np
import time
import struct
import argparse
import os


import socket

parser = argparse.ArgumentParser(description='UDP Client')
parser.add_argument('--save', action='store_true', help="Save streamed images")
args = parser.parse_args()

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

UDP_IP = "0.0.0.0"
UDP_PORT = 5001
fps_sum = 0
sock.bind((UDP_IP, UDP_PORT))
print(" Listening for UDP packets on port {}...".format(UDP_PORT))

CPX_HEADER_SIZE = 4  # 2 bytes length + 1 byte dst + 1 byte src
IMG_HEADER_MAGIC = 0xBC
IMG_HEADER_SIZE = 11  # Magic + Width + Height + Depth + Type + Size 

# Track per-address stream state
streams = {}

# Define the ESP32's IP and port
ESP32_IP = "192.168.4.1"  
ESP32_PORT = 5000           # Port on which ESP32 is listening

# Define the magic byte
MAGIC_BYTE = magic = b'FER'

# Send the magic byte to the ESP32
print(f"🔹 Sending magic byte to ESP32 at {ESP32_IP}:{ESP32_PORT}")
sock.sendto(MAGIC_BYTE, (ESP32_IP, ESP32_PORT))
count = 0
while True:
    data, addr = sock.recvfrom(2048)

    if addr not in streams:
        if len(streams) >= 3:
            print(f" Ignoring {addr} — max 3 streams reached")
            continue
        streams[addr] = {
            'buffer': bytearray(),
            'expected_size': None,
            'receiving': False,
            'packet_count': 0,
            'window_name': f"Stream from {addr[0]}:{addr[1]}",
            'last_frame_time': None
        }
        print(f" New stream: {streams[addr]['window_name']}")

    stream = streams[addr]

    # Make sure the packet is large enough to contain both the CPX header and IMG header
    # Also check magic bit (first after cpx header)
    if len(data) >= CPX_HEADER_SIZE + IMG_HEADER_SIZE and data[CPX_HEADER_SIZE] == IMG_HEADER_MAGIC:
        
        img_header_start = CPX_HEADER_SIZE
        magic = data[img_header_start]
        if magic != 0xBC:
            continue

        
        header_data = data[img_header_start + 1 : img_header_start + 1 + 10]  # width(H)+height(H)+depth(B)+fmt(B)+size(I) = 10 bytes
        width, height, depth, fmt, size = struct.unpack('<HHBBI', header_data) # Already checked magic bit, so skipped here

        
        img_start = img_header_start + 1 + 10   # after magic + 10-byte fields
        stream['buffer'] = bytearray(data[img_start:])
        stream['expected_size'] = size
        stream['receiving'] = True
        stream['packet_count'] = 1

    elif stream['receiving']:
        
        if len(data) <= CPX_HEADER_SIZE:
            continue
        stream['buffer'].extend(data[CPX_HEADER_SIZE:])
        stream['packet_count'] += 1

        if stream['expected_size'] is not None and len(stream['buffer']) >= stream['expected_size']:
            now = time.time()
            if stream['last_frame_time'] is not None:
                delta = now - stream['last_frame_time']
                fps = 1.0 / delta if delta > 0 else 0.0
                fps_sum += fps
                print(f" [{addr}] Time since last frame: {delta:.3f}s (FPS: {fps:.2f})")
            stream['last_frame_time'] = now
            # Just a bunch of debug prints
            print(f"[{addr}] Image received in {stream['packet_count']} packets")
            print(f"[{addr}] Raw buffer len: {len(stream['buffer'])} bytes")
            print(f"[{addr}] Header claimed image size: {stream['expected_size']} bytes")
            print(f"[{addr}] width={width}, height={height}, depth={depth}, fmt={fmt}")
            
            # For calculating average frame rate
            count = count+1
            try:
                if fmt == 0:
                    # If the size of the buffer doesn't match the expected size, we've (probably) lost a packet.
                    # Continue without processing the image
                    if len(stream['buffer']) != width * height * depth:
                        print(f"[{addr}] Buffer doesn't match expected size. Tossing image")
                        stream['receiving'] = False
                        continue
                    
                    
                    raw_img = np.frombuffer(stream['buffer'], dtype=np.uint8).reshape((height, width))
                    print(f"Received data shape: {raw_img.shape}")
                    print(f"AVG FPS: {fps_sum/count}")            
                    
                    
                    color_img = cv2.demosaicing(raw_img, cv2.COLOR_BayerBG2BGR_EA) # I found this to give slightly better quality than cvtColor

                    if color_img is not None:
                        
                        print(f"Shape: {color_img.shape}, dtype: {color_img.dtype}") #For debugging
                        cv2.imshow('Raw', raw_img)
                        cv2.imshow('bayer', color_img)
                        if args.save:
                            cv2.imwrite(f"stream_out/img_{count:06d}.tiff", color_img)
                        cv2.waitKey(1)
                    else:
                        print(f" [{addr}] Failed to decode image")
                # elif below is for JPEG which I don't use. I haven't tried it and can't guarantee that it works
                elif fmt == 1:
                    nparr = np.frombuffer(stream['buffer'], np.uint8)
                    decoded = color_img = cv2.demosaicing(nparr, cv2.COLOR_BayerBG2BGR_EA)
                    cv2.imshow('JPEG', decoded)
                    if args.save:
                        cv2.imwrite(f"stream_out/img_{count:06d}.tiff", decoded)
                    cv2.waitKey(1)
            except Exception as e:
                print(f" [{addr}] Decode error: {e}")

            stream['receiving'] = False
            stream['expected_size'] = None
            stream['packet_count'] = 0
