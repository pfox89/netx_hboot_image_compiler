# -*- coding: utf-8 -*-

import array
import hashlib


def patch_image(strInputFile, strOutputFile, fVerbose=False):
    if fVerbose is True:
        print('Reading the input image from "%s".' % strInputFile)

    # Read the complete input file to a string.
    tFile = open(strInputFile, 'rb')
    strInputImage = tFile.read()
    tFile.close()
    sizInputImage = len(strInputImage)

    if fVerbose is True:
        print('Read %d bytes.' % sizInputImage)

    # The input image must have at least...
    #   448 bytes of CM4 header,
    #    64 bytes of APP HBOOT header,
    #     4 bytes of application data.
    # In total this is 516 bytes.
    if sizInputImage < 516:
        raise Exception('The input image is too small. It must have at least 516 bytes.')

    # The input image must be a multiple of DWORDS.
    if (sizInputImage % 4) != 0:
        raise Exception('The size of the input image is not a multiple of DWORDS.')

    # Parse the HBOOT header as 32bit elements.
    aulHBoot = array.array('I')
    aulHBoot.fromstring(strInputImage[448:512])

    # Check the magic and signature.
    if aulHBoot[0x00] != 0xf3beaf00:
        raise Exception('The input image has no valid HBOOT magic.')
    if aulHBoot[0x06] != 0x41505041:
        raise Exception('The input image has no valid netX90 APP signature.')

    # Set flasher parameter (chip type, flash device and flash offset)
    # chip type is always netx 90, but which variant?
    # bus/unit/chip select is always 2/2/0 (intflash 2)
    # The offset is always 0.
    ucChipType = 13 # netx 90
    ucBus = 2
    ucUnit = 2
    ucCs = 0
    ulFlashDevice = 1 * ucChipType + 0x100 * ucBus + 0x10000 * ucUnit + 0x1000000 * ucCs
    ulFlashOffset = 0

    aulHBoot[0x01] = ulFlashOffset
    aulHBoot[0x05] = ulFlashDevice

    # Set the new length.
    # This is the complete file size except the CM4 header (448 bytes) and the
    # APP HBOOT header (64 bytes). The remaining size if converted from bytes
    # to DWORDS.
    sizApplicationInDwords = (sizInputImage - 512) / 4
    aulHBoot[4] = sizApplicationInDwords

    # Create a SHA384 hash over the cm4 vectors and the complete application
    # (i.e. the complete file without the first 512 bytes).
    tHash = hashlib.sha384()
    tHash.update(strInputImage[0:448])
    tHash.update(strInputImage[512:])
    aulHash = array.array('I', tHash.digest())

    # Write the first 7 DWORDs of the hash to the HBOOT header.
    aulHBoot[0x08] = aulHash[0]
    aulHBoot[0x09] = aulHash[1]
    aulHBoot[0x0a] = aulHash[2]
    aulHBoot[0x0b] = aulHash[3]
    aulHBoot[0x0c] = aulHash[4]
    aulHBoot[0x0d] = aulHash[5]
    aulHBoot[0x0e] = aulHash[6]

    # Create the header checksum.
    ulBootblockChecksum = 0
    for iCnt in range(0, 15):
        ulBootblockChecksum += aulHBoot[iCnt]
        ulBootblockChecksum &= 0xffffffff
    ulBootblockChecksum = (ulBootblockChecksum - 1) ^ 0xffffffff

    # Finalize the header with the checksum.
    aulHBoot[0x0f] = ulBootblockChecksum

    # Write the complete image to the output file.
    if fVerbose is True:
        print('Writing patched image to "%s".' % strOutputFile)
    tFile = open(strOutputFile, 'wb')
    tFile.write(strInputImage[0:448])
    aulHBoot.tofile(tFile)
    tFile.write(strInputImage[512:])
    tFile.close()

    if fVerbose is True:
        print('OK.')


if __name__ == '__main__':
    import argparse

    tParser = argparse.ArgumentParser(description='Patch the header information in a netX90 APP IFLASH image.')
    tParser.add_argument('-v', '--verbose',
                         dest='fVerbose',
                         required=False,
                         default=False,
                         action='store_const', const=True,
                         help='Be more verbose.')
    tParser.add_argument('strInputFile',
                         metavar='FILE',
                         help='Read the image from FILE.')
    tParser.add_argument('strOutputFile',
                         metavar='FILE',
                         help='Write the patched image to FILE.')
    tArgs = tParser.parse_args()

    patch_image(tArgs.strInputFile, tArgs.strOutputFile, tArgs.fVerbose)
