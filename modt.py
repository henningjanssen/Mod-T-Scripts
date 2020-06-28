#!/usr/bin/env python3

import argparse
import usb.core
import usb.util
import time
from zlib import adler32

class ModT:
    class PAYLOADS:
        BIO_GET_VERSION = (2, '{"transport":{"attrs":["request","twoway"],"id":3},"data":{"command":{"idx":0,"name":"bio_get_version"}}};')
        ENTER_DFU_MODE = (2, '{"transport":{"attrs":["request","twoway"],"id":7},"data":{"command":{"idx":53,"name":"Enter_dfu_mode"}}};')
        LOAD_INITIATE = (2, '{"transport":{"attrs":["request","twoway"],"id":9},"data":{"command":{"idx":52,"name":"load_initiate"}}};')
        STATUS = (4, '{"metadata":{"version":1,"type":"status"}}')
        UNLOAD_INITIATE = (2, '{"transport":{"attrs":["request","twoway"],"id":11},"data":{"command":{"idx":51,"name":"unload_initiate"}}};')
        WIFI_CLIENT_GET_STATUS = (2, '{"transport":{"attrs":["request","twoway"],"id":5},"data":{"command":{"idx":22,"name":"wifi_client_get_status","args":{"interface_t":0}}}};')

    def __init__(self):
        #Find the Mod-T - we should probably see if it's in DFU mode, too
        #That way we can do emergency flashes from recovery mode
        self.dev = usb.core.find(idVendor=0x2b75, idProduct=0x0002)

        #If we didn't find a Mod-T we need to throw an error
        if self.dev is None:
           raise ValueError('No Mod-T detected')

        #Set active configuration (first is default)
        self.dev.set_configuration()

        self.dev.write(2, bytearray.fromhex('246c0093ff'))

    def write(self, endpoint, message):
        self.dev.write(endpoint, message)

    def write_gcode(self, gcode, print_status=False, print_blocks=False, encoding='utf8'):
        if not isinstance(gcode, bytes):
            gcode = bytes(gcode, encoding)
        gcode_len = len(gcode)

        def adler32_hash():
            blocksize = 256*1024*1024
            hash = 0
            for ptr in range(0, gcode_len, blocksize):
                end = min(ptr+blocksize, gcode_len)
                data = gcode[ptr:end]
                hash = adler32(data, hash)
                if hash < 0:
                    hash += 2**32
            return hash

        hash = adler32_hash()
        self.write(4, '{"metadata":{"version":1,"type":"file_push"},"file_push":{"size":'+str(gcode_len)+',"adler32":'+str(hash)+',"job_id":""}}')

        # submit gcode in block and retrieve status every 20 blocks
        status_frequency = 20
        blocksize = 5120
        status_ctx = 0
        for ptr in range(0, gcode_len, blocksize):
            status_ctx += 1
            if status_ctx > 20:
                status = self.read(0x83)
                if print_status:
                    print('# printer-status:')
                    print(status)
                status_ctx = 0

            end = min(gcode_len, ptr+blocksize)
            block = gcode[ptr:end]
            print(f'# block: {ptr}-{end}, block-size: {len(block)}')
            if print_blocks:
                print(block)

            self.write(4, block)

    def write_gcode_file(self, filename, *args, **kwargs):
        with open(filename, 'rb') as f:
            gcode = f.read()
        self.write_gcode(gcode, *args, **kwargs)

    def read(self, ep):
        text = ''.join(map(chr, self.dev.read(ep, 64)))
        fulltext = text
        while len(text) == 64:
               text = ''.join(map(chr, self.dev.read(ep, 64)))
               fulltext = fulltext + text
        return fulltext

    def get_status(self):
        self.write(*self.PAYLOADS.STATUS)
        return self.read(0x83)

    def print_status(self, loop=False, loop_sleep=5):
        first_run = True
        while loop or first_run:
            print(self.get_status())
            if not loop:
                break
            time.sleep(loop_sleep)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Interact with a NewMatter Mod-T printer.')
    parser.add_argument('--no-status-loop', help='Do not print the printers status in a loop', action='store_true')

    subparsers = parser.add_subparsers(title='available sub-commands', dest='subcmd')
    subparsers.add_parser('bio_version', help='Get bio version. Seems to be equal to status.')
    subparsers.add_parser('enter_dfu', help='Enter dfu mode')

    parser_fwupdate = subparsers.add_parser('firmware_update', help='Update firmware. Not implemented. Check https://github.com/tripflex/MOD-t for firmware-versions.')
    parser_fwupdate.add_argument('file', help='DFU file containing the firmware.')

    subparsers.add_parser('load_filament', help='Load filament')

    parser_gcode = subparsers.add_parser('send_gcode', help='Send the contents of a gcode-file to the printer')
    parser_gcode.add_argument('file', help='Path to the gcode-file. Must be utf8 encoded.')
    parser_gcode.add_argument('--print-blocks', help='Print submitted blocks to screen', action='store_true')
    parser_gcode.add_argument('--print-status', help='Print the printers status every 20 blocks', action='store_true')

    subparsers.add_parser('status', help='Retrieve the printers status')
    subparsers.add_parser('unload_filament', help='Unload filament')
    subparsers.add_parser('wifi_status', help='Get wifi client status. Seems to be equal to status.')

    args = parser.parse_args()

    cmd_map = {
        'bio_version': (ModT.PAYLOADS.BIO_GET_VERSION, 0x81),
        'enter_dfu': (ModT.PAYLOADS.ENTER_DFU_MODE, None),
        'load_filament': (ModT.PAYLOADS.LOAD_INITIATE, None),
        #'status': ModT.PAYLOADS.STATUS,
        'unload_filament': (ModT.PAYLOADS.UNLOAD_INITIATE, None),
        'wifi_stats': (ModT.PAYLOADS.WIFI_CLIENT_GET_STATUS, 0x81)
    }

    try:
        printer = ModT()
    except ValueError as err:
        print(str(err))
        quit(1)

    if args.subcmd in cmd_map:
        wargs, rendpoint = cmd_map[args.subcmd]
        printer.write(*wargs)
        if rendpoint is not None:
            print(printer.read(rendpoint))
    elif args.subcmd == 'send_gcode':
        printer.write_gcode_file(args.file, args.print_status, args.print_blocks)
    elif args.subcmd == 'firmware_update':
        #This script *SHOULD* eventually be the all-encompassing firmware update
    	#It should call the check FW script, place the Mod-T into DFU mode and flash the firmware
    	#It should have a command-line arg to flash older firmware versions, none of this is really implemented yet
    	printer.write(*ModT.PAYLOADS.ENTER_DFU_MODE)

    printer.print_status(loop=(not args.no_status_loop))
