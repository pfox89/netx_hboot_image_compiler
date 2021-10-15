# -*- coding: utf-8 -*-

# Limitations:
# No define mechanism (-D)
# Limited alias mechanism (only for files), also used to replace segments and headeraddress
# No String datatype in concat.
# One or two data blocks

import argparse
import array
import base64
import binascii
from . import elf_support
import hashlib
import logging
import os
import re
import string
import subprocess
import tempfile
import xml.dom.minidom
import xml.etree.ElementTree


# Is this a standalone script?
if __name__ != '__main__':
    # No -> import the SCons module.
    import SCons.Script


class AppImage:
    # This is the environment.
    __tEnv = None

    # This is a list of all include paths.
    __astrIncludePaths = None

    # This is a dictionary of all resolved files.
    __atKnownFiles = None

    # This is a two-layer dictionary mapping ELF file paths and segment names to
    # an entry for each segment.
    # It is used to keep track of which segments have been used in a boot image.
    __tElfSegments = None

    # No data blocks yet.
    __atDataBlocks = None

    # No SDRamOffset yet.
    __ulSDRamSplitOffset = None

    __strNetxType = None

    __XmlKeyromContents = None
    __cfg_openssl = 'openssl'
    __cfg_openssloptions = None

    def __init__(self, tEnv, strNetxType, astrIncludePaths, atKnownFiles, ulSDRamSplitOffset):
        self.__tEnv = tEnv
        self.__astrIncludePaths = astrIncludePaths
        self.__atKnownFiles = atKnownFiles
        self.__ulSDRamSplitOffset = ulSDRamSplitOffset
        self.__strNetxType = strNetxType

        self.__cfg_openssl = 'openssl'
        # No SSL options yet.
        self.__cfg_openssloptions = []

    def segments_init(self):
        self.__tElfSegments = {}

    # check if the segment list for ELF is already in the list and add it, if not.
    def segments_get_elf_segments(self, strElfPath):
        if strElfPath not in self.__tElfSegments:
            atSegmentsAll = elf_support.get_segment_table(
                self.__tEnv,
                strElfPath,
                None
            )

            # construct a name to segment mapping
            tSegments = {}
            for tSegment in atSegmentsAll:
                if elf_support.segment_is_loadable(tSegment):
                    strName = elf_support.segment_get_name(tSegment)
                    ulSize = elf_support.segment_get_size(tSegment)
                    tEntry = {
                        'name': strName,
                        'size': ulSize,
                        'used': False
                    }
                tSegments[strName] = tEntry

            self.__tElfSegments[strElfPath]=tSegments

        return self.__tElfSegments[strElfPath]

    # mark a segment in an ELF file as used
    # todo: We only warn if the segment is not known in this ELF file.
    def segments_mark_used(self, strElfPath, strSegmentName):
        tSegments = self.segments_get_elf_segments(strElfPath)
        if strSegmentName in tSegments:
            tSegments[strSegmentName]['used']=True

    # mark all segments of an ELF file as used
    def segments_mark_used_all(self, strElfPath):
        tSegments = self.segments_get_elf_segments(strElfPath)
        for tSegment in tSegments.values():
            tSegment['used'] = True


    # check if there are any unused segments which contain data
    def segments_check_unused(self):
        fUnusedSegments = False
        for strElfPath, tSegments in self.__tElfSegments.items():
            for tSegment in tSegments.values():
                if tSegment['used'] != True:
                    if tSegment['size'] == 0:
                        print("Info: Unused empty segment '%s' in %s" % (tSegment['name'], strElfPath))
                    else:
                        print("Warning: Unused segment '%s' in file %s" % (tSegment['name'], strElfPath))
                        fUnusedSegments = True
        if fUnusedSegments==False:
            print("No unused segments found")
        return fUnusedSegments

    def read_keyrom(self, strKeyromFile):
        # Read the keyrom file if specified.
        if strKeyromFile is not None:
            # Parse the XML file.
            tFile = open(strKeyromFile, 'rt')
            strXml = tFile.read()
            tFile.close()
            self.__XmlKeyromContents = xml.etree.ElementTree.fromstring(strXml)

    # If strVal begins with the @ character:
    # If the remainder of the string can be resolved as an alias, return the resolved value.
    # If not, raise an error.
    # If strVal does not begin with the @ character, return strVal.
    def resolve_alias(self, strVal):
        if len(strVal)>0 and strVal[0] == '@':
            strAlias = strVal[1:]
            if strAlias in self.__atKnownFiles:
                strVal = self.__atKnownFiles[strAlias]
            else:
                raise Exception('Missing definition for alias: %s' % strAlias)

        return strVal

    # If strVal begins with the @ character:
    # If the remainder of the string can be resolved as an alias, return the resolved value.
    # If not, return the empty string.
    # If strVal does not begin with the @ character, return strVal.
    def safe_resolve_alias(self, strVal):
        if len(strVal)>0 and strVal[0] == '@':
            strAlias = strVal[1:]
            if strAlias in self.__atKnownFiles:
                strVal = self.__atKnownFiles[strAlias]
            else:
                strVal = ""
        return strVal

    def is_alias(self, strVal):
        return len(strVal)>0 and strVal[0] == '@'



    def __find_file(self, strFilePath):
        strAbsFilePath = None

        # Is this a file reference?
        if strFilePath[0] == '@':
            strFileId = strFilePath[1:]
            if strFileId in self.__atKnownFiles:
                strAbsFilePath = self.__atKnownFiles[strFileId]
        else:
            # Try the current working directory first.
            if os.access(strFilePath, os.R_OK) is True:
                strAbsFilePath = os.path.abspath(strFilePath)
            else:
                # Loop over all include folders.
                for strIncludePath in self.__astrIncludePaths:
                    strPath = os.path.abspath(
                        os.path.join(strIncludePath, strFilePath)
                    )
                    if os.access(strPath, os.R_OK) is True:
                        strAbsFilePath = strPath
                        break

        return strAbsFilePath

    def __xml_get_all_text(self, tNode):
        astrText = []
        for tChild in tNode.childNodes:
            if(
                (tChild.nodeType == tChild.TEXT_NODE) or
                (tChild.nodeType == tChild.CDATA_SECTION_NODE)
            ):
                astrText.append(str(tChild.data))
        return ''.join(astrText)

    def __remove_all_whitespace(self, strData):
        astrWhitespace = [' ', '\t', '\n', '\r']
        for strWhitespace in astrWhitespace:
            strData = strData.replace(strWhitespace, '')
        return strData

    def __parse_numeric_expression(self, strData):
        ulValue = int(strData, 0)
        return ulValue

    def __get_tag_id(self, cId0, cId1, cId2, cId3):
        # Combine the 4 ID characters to a 32 bit value.
        ulId = (
            ord(cId0) |
            (ord(cId1) << 8) |
            (ord(cId2) << 16) |
            (ord(cId3) << 24)
        )
        return ulId

    def __get_data_contents_elf(self, tNode, strAbsFilePath):
        # Get the segment names to dump. It is a comma separated string.
        # This is optional. If no segment names are specified, all sections
        # with PROGBITS are dumped.
        strSegmentsToDump = self.resolve_alias(tNode.getAttribute('segments').strip())
        astrSegmentsToDump = None
        if strSegmentsToDump==',':
            # Note: astrSegmentsToDump must be empty, not None
            astrSegmentsToDump = []
        elif len(strSegmentsToDump) != 0:
            astrSegmentsToDump = [
                strSegment.strip() for strSegment in
                string.split(strSegmentsToDump, ',')
            ]
            print('Elf file: %s  Used segments: %s' % (strAbsFilePath, strSegmentsToDump))
        else:
            print('Elf file: %s  Selecting segments automatically' % strAbsFilePath)

        # Extract the segments.
        atSegments = elf_support.get_segment_table(
            self.__tEnv,
            strAbsFilePath,
            astrSegmentsToDump
        )

        print("%d segments found" % len(atSegments))
        for tSegment in atSegments:
            print(tSegment)

        # atSegments is the list of segments contained in the elf file.
        # astrSegmentsToDump is the list of names of the segments to dump (from the XML file).

        # If astrSegmentsToDump is not None and non-empty,
        # filter the segments and the list of segments to dump.
        #
        # For each segment name in astrSegmentsToDump:
        # If the segment is not present in atSegments, print a warning and remove the name from astrSegmentsToDump.
        # If the segment is in atSegments but its size is 0, warn and remove it from astrSegmentsToDump and atSegments.
        # If the segment is in atSegments but not marked as loadable, warn and remove it from astrSegmentsToDump and atSegments.

        # If astrSegmentsToDump is None:
        # Do we have to do anything?

        if astrSegmentsToDump is not None:
            atName2Segment = dict({})
            astrSegments2 = []
            atSegments2 = []

            # prepare a segment name to segment mapping from atSegments
            for tSegment in atSegments:
                strName = elf_support.segment_get_name(tSegment)
                atName2Segment[strName]=tSegment

            for strName in astrSegmentsToDump:
                if strName not in atName2Segment:
                    print("Warning: Requested segment %s not found - ignoring" % strName )
                else:
                    tSegment = atName2Segment[strName]
                    if 0 == elf_support.segment_get_size(tSegment):
                        print("Warning: Requested segment %s is empty - ignoring" % strName )
                        self.segments_mark_used(strAbsFilePath, strName)
                    elif False == elf_support.segment_is_loadable(tSegment):
                        print("Warning: Requested segment %s is not loadable - ignoring" % strName )
                    else:
                        print("Found requested segment %s" % strName)
                        astrSegments2.append(strName)
                        atSegments2.append(tSegment)
                        self.segments_mark_used(strAbsFilePath, strName)

            astrSegmentsToDump = astrSegments2
            atSegments = atSegments2

        if len(atSegments) == 0:
            strData = ''
            pulLoadAddress = 0
            self.segments_mark_used_all(strAbsFilePath)

        else:
            # Get the estimated binary size from the segments.
            ulEstimatedBinSize = elf_support.get_estimated_bin_size(atSegments)
            # Do not create files larger than 512MB.
            if ulEstimatedBinSize >= 0x20000000:
                raise Exception('The resulting file seems to extend '
                                '512MBytes. Too scared to continue!')

            strOverwriteAddress = tNode.getAttribute(
                'overwrite_address'
            ).strip()
            if len(strOverwriteAddress) == 0:
                pulLoadAddress = elf_support.get_load_address(atSegments)
            else:
                pulLoadAddress = int(strOverwriteAddress, 0)

            # Extract the binary.
            tBinFile, strBinFileName = tempfile.mkstemp()
            os.close(tBinFile)
            astrCmd = [
                self.__tEnv['OBJCOPY'],
                '--output-target=binary'
            ]
            if astrSegmentsToDump is not None:
                for strSegment in astrSegmentsToDump:
                    astrCmd.append('--only-section=%s' % strSegment)
            astrCmd.append(strAbsFilePath)
            astrCmd.append(strBinFileName)
            subprocess.check_call(astrCmd)

            # Get the application data.
            tBinFile = open(strBinFileName, 'rb')
            strData = tBinFile.read()
            tBinFile.close()

            # Remove the temp file.
            os.remove(strBinFileName)

        return strData, pulLoadAddress

    def __get_data_contents(self, tDataNode):
        strData = None
        pulLoadAddress = None

        # Loop over all child nodes.
        for tNode in tDataNode.childNodes:
            # Is this a node element?
            if tNode.nodeType == tNode.ELEMENT_NODE:
                # Is this a "File" node?
                if tNode.localName == 'File':
                    # Get the file name.
                    strFileName = tNode.getAttribute('name')
                    if len(strFileName) == 0:
                        raise Exception(
                            "The file node has no name attribute!"
                        )

                    # Search the file in the current working folder and all
                    # include paths.
                    strAbsFilePath = self.__find_file(strFileName)
                    if strAbsFilePath is None:
                        raise Exception('File %s not found!' % strFileName)

                    # Is this an ELF file?
                    strRoot, strExtension = os.path.splitext(strAbsFilePath)
                    if strExtension == '.elf':
                        strData, pulLoadAddress = self.__get_data_contents_elf(
                            tNode,
                            strAbsFilePath
                        )

                    elif strExtension == '.bin':
                        strLoadAddress = tNode.getAttribute('load_address')
                        if len(strLoadAddress) == 0:
                            raise Exception(
                                'The File node points to a binary file '
                                'and has no load_address attribute!'
                            )

                        pulLoadAddress = self.__parse_numeric_expression(
                            strLoadAddress
                        )

                        tBinFile = open(strAbsFilePath, 'rb')
                        strData = tBinFile.read()
                        tBinFile.close()

                    else:
                        raise Exception('The File node points to a file with '
                                        'an unknown extension: %s' %
                                        strExtension)
                # Is this a node element with the name 'Hex'?
                elif tNode.localName == 'Hex':
                    strLoadAddress = tNode.getAttribute('load_address')
                    if len(strLoadAddress) == 0:
                        raise Exception(
                            'The Hex node has no load_address attribute!'
                        )

                    pulLoadAddress = self.__parse_numeric_expression(
                        strLoadAddress
                    )

                    # Get the text in this node and parse it as hex data.
                    strDataHex = self.__xml_get_all_text(tNode)
                    if strDataHex is None:
                        raise Exception('No text in node "Hex" found!')

                    strDataHex = self.__remove_all_whitespace(strDataHex)
                    strData = binascii.unhexlify(strDataHex)

                elif tNode.localName == 'UInt32':
                    strLoadAddress = tNode.getAttribute('load_address')
                    if len(strLoadAddress) == 0:
                        raise Exception(
                            'The UInt32 node has no load_address attribute!'
                        )

                    pulLoadAddress = self.__parse_numeric_expression(
                        strLoadAddress
                    )

                    # Get the text in this node and split it by whitespace.
                    strDataUint = self.__xml_get_all_text(tNode)
                    if strDataUint is None:
                        raise Exception('No text in node "UInt32" found!')

                    astrNumbers = string.split(strDataUint)
                    aulNumbers = array.array('I')
                    for strNumber in astrNumbers:
                        ulNumber = int(strNumber, 0)
                        aulNumbers.append(ulNumber)

                    strData = aulNumbers.tostring()

                elif tNode.localName == 'UInt16':
                    strLoadAddress = tNode.getAttribute('load_address')
                    if len(strLoadAddress) == 0:
                        raise Exception(
                            'The UInt16 node has no load_address attribute!'
                        )

                    pulLoadAddress = self.__parse_numeric_expression(
                        strLoadAddress
                    )

                    # Get the text in this node and split it by whitespace.
                    strDataUint = self.__xml_get_all_text(tNode)
                    if strDataUint is None:
                        raise Exception('No text in node "UInt16" found!')

                    astrNumbers = string.split(strDataUint)
                    ausNumbers = array.array('H')
                    for strNumber in astrNumbers:
                        usNumber = int(strNumber, 0)
                        ausNumbers.append(usNumber)

                    strData = ausNumbers.tostring()

                elif tNode.localName == 'UInt8':
                    strLoadAddress = tNode.getAttribute('load_address')
                    if len(strLoadAddress) == 0:
                        raise Exception(
                            'The UInt8 node has no load_address attribute!'
                        )

                    pulLoadAddress = self.__parse_numeric_expression(
                        strLoadAddress
                    )

                    # Get the text in this node and split it by whitespace.
                    strDataUint = self.__xml_get_all_text(tNode)
                    if strDataUint is None:
                        raise Exception('No text in node "UInt8" found!')

                    astrNumbers = string.split(strDataUint)
                    aucNumbers = array.array('B')
                    for strNumber in astrNumbers:
                        ucNumber = int(strNumber, 0)
                        aucNumbers.append(ucNumber)

                    strData = aucNumbers.tostring()

                elif tNode.localName == 'Concat':
                    strLoadAddress = tNode.getAttribute('load_address')
                    if len(strLoadAddress) == 0:
                        raise Exception(
                            'The Concat node has no load_address attribute!'
                        )

                    pulLoadAddress = self.__parse_numeric_expression(
                        strLoadAddress
                    )

                    astrData = []

                    # Loop over all sub-nodes.
                    for tConcatNode in tNode.childNodes:
                        # Is this a node element?
                        if tConcatNode.nodeType == tConcatNode.ELEMENT_NODE:
                            # Is this a node element with the name 'Hex'?
                            if tConcatNode.localName == 'Hex':
                                # Get the text in this node and parse it
                                # as hex data.
                                strDataHex = self.__xml_get_all_text(
                                    tConcatNode
                                )
                                if strDataHex is None:
                                    raise Exception('No text in node '
                                                    '"Hex" found!')

                                strDataHex = self.__remove_all_whitespace(
                                    strDataHex
                                )
                                strDataChunk = binascii.unhexlify(strDataHex)
                                astrData.append(strDataChunk)

                            elif tConcatNode.localName == 'UInt32':
                                # Get the text in this node and split it
                                # by whitespace.
                                strDataUint = self.__xml_get_all_text(
                                    tConcatNode
                                )
                                if strDataUint is None:
                                    raise Exception('No text in node '
                                                    '"UInt32" found!')

                                astrNumbers = string.split(strDataUint)
                                aulNumbers = array.array('I')
                                for strNumber in astrNumbers:
                                    ulNumber = int(strNumber, 0)
                                    aulNumbers.append(ulNumber)

                                strDataChunk = aulNumbers.tostring()
                                astrData.append(strDataChunk)

                            elif tConcatNode.localName == 'UInt16':
                                # Get the text in this node and split it
                                # by whitespace.
                                strDataUint = self.__xml_get_all_text(
                                    tConcatNode
                                )
                                if strDataUint is None:
                                    raise Exception('No text in node '
                                                    '"UInt16" found!')

                                astrNumbers = string.split(strDataUint)
                                ausNumbers = array.array('H')
                                for strNumber in astrNumbers:
                                    usNumber = int(strNumber, 0)
                                    ausNumbers.append(usNumber)

                                strDataChunk = ausNumbers.tostring()
                                astrData.append(strDataChunk)

                            elif tConcatNode.localName == 'UInt8':
                                # Get the text in this node and split it
                                # by whitespace.
                                strDataUint = self.__xml_get_all_text(
                                    tConcatNode
                                )
                                if strDataUint is None:
                                    raise Exception('No text in node "UInt8" '
                                                    ' found!')

                                astrNumbers = string.split(strDataUint)
                                aucNumbers = array.array('B')
                                for strNumber in astrNumbers:
                                    ucNumber = int(strNumber, 0)
                                    aucNumbers.append(ucNumber)

                                strDataChunk = aucNumbers.tostring()
                                astrData.append(strDataChunk)

                    strData = ''.join(astrData)

                else:
                    raise Exception('Unexpected node: %s' % tNode.localName)

        # Check if all parameters are there.
        if strData is None:
            raise Exception('No data specified!')
        if pulLoadAddress is None:
            raise Exception('No load address specified!')

        return strData, pulLoadAddress

    def __cert_parse_binding(self, tNodeParent, strName):
        # The binding is not yet set.
        strBinding = None

        # Loop over all child nodes.
        for tNode in tNodeParent.childNodes:
            if(
                (tNode.nodeType == tNode.ELEMENT_NODE) and
                (tNode.localName == strName)
            ):
                strBinding = self.__xml_get_all_text(tNode)

        if strBinding is None:
            raise Exception('No "%s" node found!' % strName)

        strBinding = self.__remove_all_whitespace(strBinding)
        aucBinding = array.array('B', binascii.unhexlify(strBinding))
        sizBinding = len(aucBinding)

        # A binding block has a size of 28 bytes on the netX90.
        sizBindingExpected = 28

        if sizBinding != sizBindingExpected:
            raise Exception('The binding in node "%s" has an invalid size '
                            'of %d bytes.' % (strName, sizBinding))

        return aucBinding

    # This function gets a data block from the OpenSSL output.
    def __openssl_get_data_block(self, strStdout, strID):
        aucData = array.array('B')
        tReData = re.compile('^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2})*:?$')
        iState = 0
        for strLine in iter(strStdout.splitlines()):
            strLine = string.strip(strLine)
            if iState == 0:
                if strLine == strID:
                    iState = 1
            elif iState == 1:
                tMatch = tReData.search(strLine)
                if tMatch is None:
                    break
                else:
                    for strDataHex in string.split(strLine, ':'):
                        strDataHexStrip = string.strip(strDataHex)
                        if len(strDataHexStrip)!=0:
                            strDataBin = binascii.unhexlify(strDataHexStrip)
                            aucData.append(ord(strDataBin))

        return aucData

    def __openssl_cut_leading_zero(self, aucData):
        # Does the number start with "00" and is the third digit >= 8?
        if aucData[0]==0x00 and aucData[1]>=0x80:
            # Remove the leading "00".
            aucData.pop(0)

    def __openssl_convert_to_little_endian(self, aucData):
        aucData.reverse()

    def __openssl_uncompress_field(self, aucData):
        # The data must not be compressed.
        if aucData[0]!=0x04:
            raise Exception('The data is compressed. This is not supported yet.')
        # Cut off the first byte.
        aucData.pop(0)

    def __openssl_cut_in_half(self, aucData):
        # Cut the public key in equal parts.
        sizDataHalf = len(aucData) / 2
        aucData0 = array.array('B', aucData[:sizDataHalf])
        aucData1 = array.array('B', aucData[sizDataHalf:])
        return aucData0, aucData1

    def __keyrom_get_key(self, uiIndex):
        # This needs the keyrom data.
        if self.__XmlKeyromContents is None:
            raise Exception('No Keyrom contents specified!')

        # Find the requested key and hash.
        tNode = self.__XmlKeyromContents.find('Entry/[@index="%d"]' % uiIndex)
        if tNode is None:
            raise Exception('Key %d was not found!' % uiIndex)
        tNode_key = tNode.find('Key')
        if tNode_key is None:
            raise Exception('Key %d has no "Key" child!' % uiIndex)
        tNode_hash = tNode.find('Hash')
        if tNode_hash is None:
            raise Exception('Key %d has no "Hash" child!' % uiIndex)

        strKeyBase64 = tNode_key.text

        # Decode the BASE64 data. Now we have the key pair in DER format.
        strKeyDER = base64.b64decode(strKeyBase64)

        return strKeyDER

    def __get_cert_mod_exp(self, tNodeParent, strKeyDER, fIsPublicKey):
        # Extract all information from the key.
        astrCmd = [
            self.__cfg_openssl,
            'pkey',
            '-inform',
            'DER',
            '-text',
            '-noout'
        ]
        if fIsPublicKey is True:
            astrCmd.append('-pubin')
        tProcess = subprocess.Popen(
            astrCmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        (strStdout, strStdErr) = tProcess.communicate(strKeyDER)
        if tProcess.returncode != 0:
            raise Exception('OpenSSL failed with return code %d.' %
                            tProcess.returncode)

        # Try to guess if this is an RSA or ECC key.
        # The text dump of an RSA key has " modulus:", while an ECC key has
        # "priv:".
        iKeyTyp_1ECC_2RSA = None
        atAttr = None
        if string.find(strStdout, 'modulus:') != -1:
            # Looks like this is an RSA key.
            iKeyTyp_1ECC_2RSA = 2

            strMatchExponent = 'publicExponent:'
            strMatchModulus = 'modulus:'
            if fIsPublicKey is True:
                strMatchExponent = 'Exponent:'
                strMatchModulus = 'Modulus:'

            # Extract the public exponent.
            tReExp = re.compile(
                '^%s\s+(\d+)\s+\(0x([0-9a-fA-F]+)\)$' % strMatchExponent,
                re.MULTILINE
            )
            tMatch = tReExp.search(strStdout)
            if tMatch is None:
                raise Exception('Can not find public exponent!')
            ulExp = int(tMatch.group(1))
            ulExpHex = int(tMatch.group(2), 16)
            if ulExp != ulExpHex:
                raise Exception('Decimal version differs from hex version!')
            if (ulExp < 0) or (ulExp > 0xffffff):
                raise Exception('The exponent exceeds the allowed range of a '
                                '24bit unsigned integer!')
            strData = (
                chr(ulExp & 0xff) +
                chr((ulExp >> 8) & 0xff) +
                chr((ulExp >> 16) & 0xff)
            )
            aucExp = array.array('B', strData)

            # Extract the modulus "N".
            aucMod = self.__openssl_get_data_block(strStdout, strMatchModulus)
            self.__openssl_cut_leading_zero(aucMod)
            self.__openssl_convert_to_little_endian(aucMod)

            __atKnownRsaSizes = {
                0: {'mod': 256, 'exp': 3, 'rsa': 2048},
                1: {'mod': 384, 'exp': 3, 'rsa': 3072},
                2: {'mod': 512, 'exp': 3, 'rsa': 4096}
            }

            sizMod = len(aucMod)
            sizExp = len(aucExp)
            uiId = None
            for uiElementId, atAttr in __atKnownRsaSizes.iteritems():
                if (sizMod == atAttr['mod']) and (sizExp == atAttr['exp']):
                    uiId = uiElementId + 1
                    break

            if uiId is None:
                strErr = (
                    'The modulo has a size of %d bytes. '
                    'The public exponent has a size of %d bytes.\n'
                    'These values can not be mapped to a RSA bit size. '
                    'Known sizes are:\n' % (
                        sizMod,
                        sizExp
                    )
                )
                for uiElementId, atAttr in __atKnownRsaSizes.iteritems():
                    strErr += (
                        '  RSA%d: %d bytes modulo, %d bytes public exponent\n' %
                        (atAttr['rsa'], atAttr['mod'], atAttr['exp'])
                    )
                raise Exception(strErr)

            atAttr = {
                'id': uiId,
                'mod': aucMod,
                'exp': aucExp
            }

        elif string.find(strStdout, 'priv:') != -1:
            # Looks like this is an ECC key.
            iKeyTyp_1ECC_2RSA = 1

            aucPriv = self.__openssl_get_data_block(strStdout, 'priv:')
            self.__openssl_cut_leading_zero(aucPriv)
            self.__openssl_convert_to_little_endian(aucPriv)

            aucPub = self.__openssl_get_data_block(strStdout, 'pub:')
            self.__openssl_uncompress_field(aucPub)
            aucPubX, aucPubY = self.__openssl_cut_in_half(aucPub)
            self.__openssl_convert_to_little_endian(aucPubX)
            self.__openssl_convert_to_little_endian(aucPubY)

            aucPrime = self.__openssl_get_data_block(strStdout, 'Prime:')
            self.__openssl_cut_leading_zero(aucPrime)
            self.__openssl_convert_to_little_endian(aucPrime)

            aucA = self.__openssl_get_data_block(strStdout, 'A:')
            self.__openssl_cut_leading_zero(aucA)
            self.__openssl_convert_to_little_endian(aucA)

            aucB = self.__openssl_get_data_block(strStdout, 'B:')
            self.__openssl_cut_leading_zero(aucB)
            self.__openssl_convert_to_little_endian(aucB)

            strData = self.__openssl_get_data_block(strStdout, 'Generator (uncompressed):')
            aucGen = array.array('B', strData)
            self.__openssl_uncompress_field(aucGen)
            aucGenX, aucGenY = self.__openssl_cut_in_half(aucGen)
            self.__openssl_convert_to_little_endian(aucGenX)
            self.__openssl_convert_to_little_endian(aucGenY)

            aucOrder = self.__openssl_get_data_block(strStdout, 'Order:')
            self.__openssl_cut_leading_zero(aucOrder)
            self.__openssl_convert_to_little_endian(aucOrder)

            # Extract the cofactor.
            tReExp = re.compile('^Cofactor:\s+(\d+)\s+\(0x([0-9a-fA-F]+)\)$', re.MULTILINE)
            tMatch = tReExp.search(strStdout)
            if tMatch is None:
                raise Exception('Can not find cofactor!')
            ulCofactor = long(tMatch.group(1))
            ulCofactorHex = long(tMatch.group(2), 16)
            if ulCofactor!=ulCofactorHex:
                raise Exception('Decimal version differs from hex version!')

            __atKnownEccSizes = {
                0: 32,
                1: 48,
                2: 64
            }

            sizD = len(aucPriv)
            sizQx = len(aucPubX)
            sizQy = len(aucPubY)
            sizP = len(aucPrime)
            sizA = len(aucA)
            sizB = len(aucB)
            sizGx = len(aucGenX)
            sizGy = len(aucGenY)
            sizN = len(aucOrder)
            uiId = None
            for uiElementId, sizNumbers in __atKnownEccSizes.iteritems():
                if(
                    (sizNumbers == sizD) and
                    (sizNumbers == sizQx) and
                    (sizNumbers == sizQy) and
                    (sizNumbers == sizP) and
                    (sizNumbers == sizA) and
                    (sizNumbers == sizB) and
                    (sizNumbers == sizGx) and
                    (sizNumbers == sizGy) and
                    (sizNumbers == sizN)
                ):
                    # Found the ECC type.
                    uiId = uiElementId + 1
                    break

            if uiId is None:
                raise Exception('Invalid ECC key.')

            atAttr = {
                'id': uiId,
                'd': aucPriv,
                'Qx': aucPubX,
                'Qy': aucPubY,
                'p': aucPrime,
                'a': aucA,
                'b': aucB,
                'Gx': aucGenX,
                'Gy': aucGenY,
                'n': aucOrder,
                'cof': ulCofactor
            }

        else:
            raise Exception('Unknown key format.')

        return iKeyTyp_1ECC_2RSA, atAttr

    def __usip_parse_trusted_path(self, tNodeParent, atData):
        strKeyDER = None
        # Get the index.
        strIdx = tNodeParent.getAttribute('idx')
        if len(strIdx) != 0:
            ulIdx = self.__parse_numeric_expression(strIdx)

            # Get the key in DER encoded format.
            strKeyDER = self.__keyrom_get_key(ulIdx)

        else:
            # Search for a "File" child node.
            tFileNode = None
            for tNode in tNodeParent.childNodes:
                if(
                    (tNode.nodeType == tNode.ELEMENT_NODE) and
                    (tNode.localName == 'File')
                ):
                    tFileNode = tNode
                    break
            if tFileNode is not None:
                strFileName = tFileNode.getAttribute('name')

                # Search the file in the current path and all include paths.
                strAbsName = self.__find_file(strFileName)
                if strAbsName is None:
                    raise Exception(
                        'Failed to read file "%s": file not found.' %
                        strFileName
                    )

                # Read the complete key.
                tFile = open(strAbsName, 'rb')
                strKeyDER = tFile.read()
                tFile.close()

        if strKeyDER is None:
            raise Exception('No "idx" attribute and no child "File" found!')

        iKeyTyp_1ECC_2RSA, atAttr = self.__get_cert_mod_exp(
            tNodeParent,
            strKeyDER,
            False
        )

        atData['iKeyTyp_1ECC_2RSA'] = iKeyTyp_1ECC_2RSA
        atData['atAttr'] = atAttr
        atData['der'] = strKeyDER

    def __build_chunk_asig(self, tChunkNode):
        aulChunk = None

        # Generate an array with default values where possible.
        __atCert = {
            # The key must be set by the user.
            'Key': {
                'type': None,
                'id': None,
                'mod': None,
                'exp': None,
                'der': None
            },

            # The Binding must be set by the user.
            'Binding': {
                'mask': None,
                'ref': None
            }
        }

        # Loop over all children.
        for tNode in tChunkNode.childNodes:
            if tNode.nodeType == tNode.ELEMENT_NODE:
                if tNode.localName == 'Key':
                    self.__usip_parse_trusted_path(tNode, __atCert['Key'])

                elif tNode.localName == 'Binding':
                    __atCert['Binding']['value'] = self.__cert_parse_binding(
                        tNode,
                        'Value'
                    )
                    __atCert['Binding']['mask'] = self.__cert_parse_binding(
                        tNode,
                        'Mask'
                    )

                else:
                    raise Exception('Unexpected node: %s' %
                                    tNode.localName)

        # Check if all required data was set.
        astrErr = []
        if __atCert['Key']['der'] is None:
            astrErr.append('No key set in USIP.')
        if __atCert['Binding']['mask'] is None:
            astrErr.append('No "mask" set in the Binding.')
        if __atCert['Binding']['value'] is None:
            astrErr.append('No "value" set in the Binding.')
        if len(astrErr) != 0:
            raise Exception('\n'.join(astrErr))

        iKeyTyp_1ECC_2RSA = __atCert['Key']['iKeyTyp_1ECC_2RSA']
        atAttr = __atCert['Key']['atAttr']
        if iKeyTyp_1ECC_2RSA == 1:
            sizKeyInDwords = len(atAttr['Qx']) / 4
            sizSignatureInDwords = 2 * sizKeyInDwords
        elif iKeyTyp_1ECC_2RSA == 2:
            sizKeyInDwords = len(atAttr['mod']) / 4
            sizSignatureInDwords = sizKeyInDwords

        # The size of the ASIG thing without the signature is...
        #   4 bytes ID
        #   4 bytes length
        #  56 bytes binding
        #  48 bytes hash
        #----------------------
        # 112 bytes or
        #  28 DWORDs

        # Combine all data to the chunk.
        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('A', 'S', 'I', 'G'))
        aulChunk.append(28 + sizSignatureInDwords)

        # Add the binding.
        aulChunk.fromstring(__atCert['Binding']['value'].tostring())
        aulChunk.fromstring(__atCert['Binding']['mask'].tostring())

        # Build a hash over the first part of the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tostring())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash)
        aulChunk.extend(aulHash)

        # Get the key in DER encoded format.
        strKeyDER = __atCert['Key']['der']

        # Create a temporary file for the keypair.
        iFile, strPathKeypair = tempfile.mkstemp(
            suffix='der',
            prefix='tmp_hboot_image',
            dir=None,
            text=False
        )
        os.close(iFile)

        # Create a temporary file for the data to sign.
        iFile, strPathSignatureInputData = tempfile.mkstemp(
            suffix='bin',
            prefix='tmp_hboot_image',
            dir=None,
            text=False
        )
        os.close(iFile)

        # Write the DER key to the temporary file.
        tFile = open(strPathKeypair, 'wt')
        tFile.write(strKeyDER)
        tFile.close()

        # Write the data to sign to the temporary file.
        tFile = open(strPathSignatureInputData, 'wb')
        aulChunk0Data = self.__atDataBlocks[0]['data']
        tFile.write(aulChunk0Data[0:112])
        tFile.write(aulChunk0Data[128:])
        sizDataBlocks = len(self.__atDataBlocks)
        for sizCnt in range(1, sizDataBlocks):
            tFile.write(self.__atDataBlocks[sizCnt]['header'])
            tFile.write(self.__atDataBlocks[sizCnt]['data'])
        tFile.close()

        if iKeyTyp_1ECC_2RSA == 1:
            astrCmd = [
                self.__cfg_openssl,
                'dgst',
                '-sign', strPathKeypair,
                '-keyform', 'DER',
                '-sha384'
            ]
            astrCmd.extend(self.__cfg_openssloptions)
            astrCmd.append(strPathSignatureInputData)
            strEccSignature = subprocess.check_output(astrCmd)
            aucEccSignature = array.array('B', strEccSignature)

            # Parse the signature.
            aucSignature = self.__openssl_ecc_get_signature(aucEccSignature, sizKeyInDwords * 4)

        elif iKeyTyp_1ECC_2RSA == 2:
            astrCmd = [
                self.__cfg_openssl,
                'dgst',
                '-sign', strPathKeypair,
                '-keyform', 'DER',
                '-sigopt', 'rsa_padding_mode:pss',
                '-sigopt', 'rsa_pss_saltlen:-1',
                '-sha384'
            ]
            astrCmd.extend(self.__cfg_openssloptions)
            astrCmd.append(strPathSignatureInputData)
            strSignatureMirror = subprocess.check_output(astrCmd)
            aucSignature = array.array('B', strSignatureMirror)
            # Mirror the signature.
            aucSignature.reverse()

        # Remove the temp files.
        os.remove(strPathKeypair)
        os.remove(strPathSignatureInputData)

        # Append the signature to the chunk.
        aulChunk.fromstring(aucSignature.tostring())

        return aulChunk

    ROMLOADER_CHIPTYP_NETX90_MPW           = 10
    ROMLOADER_CHIPTYP_NETX90               = 13
    ROMLOADER_CHIPTYP_NETX90B              = 14

    atChipTypeMapping = {
        # These names are for compatibility with the COM side HBoot image tool
        # 'NETX90':     ROMLOADER_CHIPTYP_NETX90,
        # 'NETX90B':    ROMLOADER_CHIPTYP_NETX90B,
        # 'NETX90_MPW': ROMLOADER_CHIPTYP_NETX90_MPW,
        # These names are for compatibility with the netx 90 HWConfig tool.
        'netx90':     ROMLOADER_CHIPTYP_NETX90B,  # Alias for the latest chip revision.
        'netx90_rev0':ROMLOADER_CHIPTYP_NETX90,
        'netx90_rev1':ROMLOADER_CHIPTYP_NETX90B,
        'netx90_mpw': ROMLOADER_CHIPTYP_NETX90_MPW,
    }

    BUS_SPI = 1
    BUS_IFlash = 2
    atDeviceMapping_netx90 = [
        {'name': 'INTFLASH2', 'start': 0x00000000, 'end': 0x0007ffff, 'bus':BUS_IFlash, 'unit':2, 'chip_select':0},
        {'name': 'SQIROM',    'start': 0x64000000, 'end': 0x67ffffff, 'bus':BUS_SPI,    'unit':0, 'chip_select':0},
        ]

    # Insert information for use by the flasher:
    # chip type, target flash device and flash offset.
    def __set_flasher_parameters(self, aulHBoot, ulHeaderAddress):
        if self.__strNetxType not in self.atChipTypeMapping:
            raise Exception("Cannot set flasher parameters for chip type %s" % self.__strNetxType)
        ucChipType = self.atChipTypeMapping[self.__strNetxType]

        tDevInfo = None
        for tDev in self.atDeviceMapping_netx90:
            if tDev['start'] <= ulHeaderAddress and ulHeaderAddress <= tDev['end']:
               tDevInfo = tDev
               break

        if tDevInfo == None:
            raise Exception('No device found for header address 0x%08x' % ulHeaderAddress)

        print ('Found flash device %s for address 0x%08x' % (tDevInfo['name'], ulHeaderAddress))

        ulFlashDevice = 1 * ucChipType + 0x100 * tDevInfo['bus'] + 0x10000 * tDevInfo['unit'] + 0x1000000 * tDevInfo['chip_select']
        ulFlashOffset = ulHeaderAddress

        aulHBoot[0x01] = ulFlashOffset
        aulHBoot[0x05] = ulFlashDevice

    def patch_first_data_block(self):
        sizDataBlocks = len(self.__atDataBlocks)
        tAttr = self.__atDataBlocks[0]
        aulInputImage = tAttr['data']
        sizInputImageDWORDs = len(aulInputImage)

        # The input image must have at least...
        #   448 bytes of CM4 header,
        #    64 bytes of APP HBOOT header,
        #     4 bytes of application data.
        # In total this is 516 bytes or 129 DWORDs.
        if sizInputImageDWORDs < 129:
            raise Exception(
                'The first data block is too small. '
                'It must have at least 516 bytes.'
            )

        # Extract the HBOOT header.
        aulHBoot = array.array('I')
        aulHBoot.fromstring(aulInputImage[112:128])

        # Check the magic and signature.
        if aulHBoot[0x00] != 0xf3beaf00:
            raise Exception('The input image has no valid HBOOT magic.')
        if aulHBoot[0x06] != 0x41505041:
            raise Exception(
                'The input image has no valid netX90 APP signature.'
            )

        # Set the next pointer.
        if sizDataBlocks == 1:
            aulHBoot[2] = 0
        else:
            aulHBoot[2] = self.__atDataBlocks[1]['headeraddress']

        # Set the new length.
        # This is the complete file size except the CM4 header (448 bytes)
        # and the APP HBOOT header (64 bytes). The remaining size if converted
        # from bytes to DWORDS.
        sizApplicationInDwords = sizInputImageDWORDs - 128
        aulHBoot[4] = sizApplicationInDwords

        # Offset 5+1: set the destination device and offset for the flasher.
        ulHeaderAddress = self.__atDataBlocks[0]['headeraddress']
        self.__set_flasher_parameters(aulHBoot, ulHeaderAddress)

        # Create a SHA384 hash over the cm4 vectors, the complete application
        # and all other blocks.
        # (i.e. everything except the first header).
        tHash = hashlib.sha384()
        tHash.update(aulInputImage[0:112])
        tHash.update(aulInputImage[128:])
        for sizCnt in range(1, sizDataBlocks):
            tHash.update(self.__atDataBlocks[sizCnt]['header'])
            tHash.update(self.__atDataBlocks[sizCnt]['data'])
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

        # Copy the header into the data.
        for iCnt in range(0, 16):
            aulInputImage[112 + iCnt] = aulHBoot[iCnt]

        tAttr['data'] = aulInputImage

    def build_header(self, sizIdx):
        # Get the attributes.
        tAttr = self.__atDataBlocks[sizIdx]

        # Create an empty array.
        aulHBoot = array.array('I', [0] * 16)

        # Set the magic cookie.
        aulHBoot[0] = 0xf3beaf00

        # Set the next pointer.
        sizDataBlocks = len(self.__atDataBlocks)
        if sizIdx + 1 >= sizDataBlocks:
            aulHBoot[2] = 0
        else:
            aulHBoot[2] = self.__atDataBlocks[sizIdx + 1]['headeraddress']

        # Is the block XIP?
        if tAttr['destination'] == tAttr['headeraddress'] + 64:
            aulHBoot[3] = 0
        # Is the block in the SDRAM?
        elif (tAttr['destination'] >= 0x10000000) and (tAttr['destination'] < 0x20000000):
            aulHBoot[3] = tAttr['destination'] + self.__ulSDRamSplitOffset
        else:
            aulHBoot[3] = 0


        # Set the data size in DWORDs.
        aulHBoot[4] = len(tAttr['data'])

        # Offset 5+1: set the destination device and offset for the flasher.
        ulHeaderAddress = tAttr['headeraddress']
        self.__set_flasher_parameters(aulHBoot, ulHeaderAddress)

        # Set the signature.
        aulHBoot[6] = 0x41505041

        # Offset 7: image parameter
        # Keep at 0.

        # Offsets 8-14 store the hash, which is only valid for the first
        # header.
        # Keep at 0.

        # Create the header checksum.
        ulBootblockChecksum = 0
        for iCnt in range(0, 15):
            ulBootblockChecksum += aulHBoot[iCnt]
            ulBootblockChecksum &= 0xffffffff
        ulBootblockChecksum = (ulBootblockChecksum - 1) ^ 0xffffffff

        aulHBoot[15] = ulBootblockChecksum

        tAttr['header'] = aulHBoot

    # If the output file name is omitted, there must not be a segment list specified.
    # The segment list attribute must be either
    # - absent
    # - empty
    # - ","
    # - not resolvable
    # If the attribute is present and
    # - contains a non-alias value (other than ",")
    # - or contains an alias that can be resolved,
    # raise an error.
    def data_node_check_no_segments(self, tNodeData):
        #print("*** data_node_check_no_segments *****")
        for tNodeChild in tNodeData.childNodes:
            #print (tNodeChild.localName)
            if tNodeChild.localName == 'File':
                strVal = tNodeChild.getAttribute('segments').strip()
                strVal2 = self.safe_resolve_alias(strVal)
                #print("segments: %s -> %s" % (strVal, strVal2))
                if len(strVal2)>0 and strVal2!=',':
                    #print("Exception")
                    # Error, no segment list should be supplied
                    raise Exception ('Output filename is empty but a segment list is specified')
                #else:
                #    print("Accept")

    def process_app_image(self, strSourcePath, astrDestinationPaths):
        # No data blocks yet.
        self.__atDataBlocks = []

        self.segments_init()

        tXml = xml.dom.minidom.parse(strSourcePath)
        tNodeRoot = tXml.documentElement
        if tNodeRoot.localName != 'AppImage':
            raise Exception('Unexpected root tag!')

        # Loop over all data elements.
        tNodeAsig = None

        # Offset into the list of output file paths
        iDestPathIndex = 0

        for tNodeChild in tNodeRoot.childNodes:
            if tNodeChild.localName == 'data':
                if iDestPathIndex >= len(astrDestinationPaths):
                    print('Skipping data node because no output file name is supplied')
                    self.data_node_check_no_segments(tNodeChild)

                elif astrDestinationPaths[iDestPathIndex] == '':
                    iDestPathIndex = iDestPathIndex + 1
                    print('destination path: %d >%s<' % (iDestPathIndex, ''))
                    print('Skipping data node because output file name is empty')
                    self.data_node_check_no_segments(tNodeChild)

                else:
                    strDesinationPath = astrDestinationPaths[iDestPathIndex]
                    iDestPathIndex = iDestPathIndex + 1
                    print('destination path: %d >%s<' % (iDestPathIndex, strDesinationPath))

                    # Get one data block.
                    strData, pulLoadAddress = self.__get_data_contents(tNodeChild)
                    # The input image must be a multiple of DWORDS.
                    if (len(strData) % 4) != 0:
                        raise Exception(
                            'The size of the input image is not a multiple of DWORDS.'
                        )
                    # Convert the data to an array.
                    aulData = array.array('I')
                    aulData.fromstring(strData)

                    # Get the header address.
                    if tNodeChild.hasAttribute('headeraddress') is not True:
                        raise Exception('Missing "headeraddress" attribute.')
                    strHeaderAddress = self.resolve_alias(tNodeChild.getAttribute('headeraddress'))
                    ulHeaderAddress = int(strHeaderAddress, 0)
                    if ulHeaderAddress is None:
                        raise Exception(
                            'Failed to parse number: "%s".',
                            strHeaderAddress
                        )

                    # Get the padding.
                    ulPaddingPreSize = 0
                    ucPaddingPreValue = 0xff
                    strPaddingPreSize = tNodeChild.getAttribute('padding_pre_size')
                    if len(strPaddingPreSize) != 0:
                        ulPaddingPreSize = int(strPaddingPreSize, 0)
                        if ulPaddingPreSize < 0:
                            raise Exception(
                                'The padding pre size is invalid: %d' % ulPaddingPreSize
                            )
                    strPaddingPreValue = tNodeChild.getAttribute('padding_pre_value')
                    if len(strPaddingPreValue) != 0:
                        ucPaddingPreValue = int(strPaddingPreValue, 0)
                        if (ucPaddingPreValue < 0) or (ucPaddingPreValue > 0xff):
                            raise Exception(
                                'The padding pre value is invalid: %d' % ucPaddingPreValue
                            )

                    tAttr = {
                        'prePaddingSize': ulPaddingPreSize,
                        'prePaddingValue': ucPaddingPreValue,
                        'header': None,
                        'data': aulData,
                        'headeraddress': ulHeaderAddress,
                        'destination': pulLoadAddress,
                        'asig': None,
                        'destinationPath': strDesinationPath
                    }
                    self.__atDataBlocks.append(tAttr)

            elif tNodeChild.localName == 'asig':
                if tNodeAsig is not None:
                    raise Exception('More than one "asig" node found.')
                tNodeAsig = tNodeChild

        # There must be at least one data block.
        sizDataBlocks = len(self.__atDataBlocks)
        if sizDataBlocks == 0:
            raise Exception('No data blocks found.')

        # Raise an error if there are any unused output file paths remaining
        if len(astrDestinationPaths) > iDestPathIndex:
            raise Exception(
                '%d output files specified, but only %d were used' %
                (len(astrDestinationPaths), iDestPathIndex)
                )

        # Check if any loadable segments recorded for the elf file(s) have not been used
        if True == self.segments_check_unused():
            raise Exception('There are unused segments containing data')

        # The first header must have a header address of 0x00000000.
        tFirstAttr = self.__atDataBlocks[0]
        if tFirstAttr['headeraddress'] != 0x00000000:
            raise Exception(
                'The first data block must have a header address of '
                '0x00000000, but it has 0x%08x.' %
                tFirstAttr['headeraddress']
            )

        # Build headers for all data blocks after the first one.
        for sizIdx in range(1, sizDataBlocks):
            self.build_header(sizIdx)

        # Patch the first data block.
        self.patch_first_data_block()

        # Append ASIG thing to the last block if requested.
        if tNodeAsig is not None:
            tAttr = self.__atDataBlocks[-1]
            tAttr['asig'] = self.__build_chunk_asig(tNodeAsig)

        # Write the data blocks.
        for iCnt in range(0, len(self.__atDataBlocks)):
            tAttr = self.__atDataBlocks[iCnt]
            strDestinationPath = tAttr['destinationPath']

            print('Writing file %s' % strDestinationPath)
            tFile = open(strDestinationPath, 'wb')

            ulPrePaddingSize = tAttr['prePaddingSize']
            ucPrePaddingValue = tAttr['prePaddingValue']
            if ulPrePaddingSize != 0:
                aucPrePad = array.array('B', [ucPrePaddingValue] * ulPrePaddingSize)
                aucPrePad.tofile(tFile)

            aucData = tAttr['header']
            if aucData is not None:
                aucData.tofile(tFile)

            aucData = tAttr['data']
            if aucData is not None:
                aucData.tofile(tFile)

            aucData = tAttr['asig']
            if aucData is not None:
                aucData.tofile(tFile)

            tFile.close()


def __get_clean_known_files(atKnownFiles):
    atClean = {}

    # Iterate over all known files.
    for strKey, tFile in atKnownFiles.items():
        # The file must be either a string, a SCons.Node.FS.File object or a
        # SCons.Node.NodeList object.
        if isinstance(tFile, str):
            strFile = tFile
        elif isinstance(tFile, SCons.Node.FS.File):
            strFile = tFile.get_path()
        elif isinstance(tFile, SCons.Node.NodeList):
            # The list must have exactly one entry.
            if len(tFile) != 1:
                raise Exception(
                    'Key "%s" has more than one file in the known files.' %
                    strKey
                )
            strFile = tFile[0].get_path()
        else:
            raise Exception(
                'Unknown type for key "%s" in the known files.' %
                strKey
            )

        atClean[strKey] = strFile

    return atClean


def __app_image_action(target, source, env):
    atKnownFiles = {}
    if 'APPIMAGE_KNOWN_FILES' in env:
        atK = env['APPIMAGE_KNOWN_FILES']
        if atK is not None:
            atKnownFiles = __get_clean_known_files(atK)

    astrIncludePaths = []
    if 'APPIMAGE_INCLUDE_PATHS' in env:
        atValues = env['APPIMAGE_INCLUDE_PATHS']
        if (atValues is not None) and (len(atValues) != 0):
            astrIncludePaths.extend(atValues)

    # fVerbose = False
    # if 'APPIMAGE_VERBOSE' in env:
    #    fVerbose = bool(env['APPIMAGE_VERBOSE'])

    strKeyRomPath = None
    if 'APPIMAGE_KEYROM_XML' in env:
        strKeyRomPath = env['APPIMAGE_KEYROM_XML']

    strSourcePath = source[0].get_path()
    astrDestinationPaths = []
    for tTarget in target:
        astrDestinationPaths.append(tTarget.get_path())

    tAppImage = AppImage(env, astrIncludePaths, atKnownFiles)
    if strKeyRomPath is not None:
        tAppImage.read_keyrom(strKeyRomPath)

    tAppImage.process_app_image(
        strSourcePath,
        astrDestinationPaths
    )

    return 0


def __app_image_emitter(target, source, env):
    if 'APPIMAGE_KNOWN_FILES' in env:
        atKnownFiles = env['APPIMAGE_KNOWN_FILES']
        if atKnownFiles is not None:
            atKnownFiles = __get_clean_known_files(atKnownFiles)
            for strId, strPath in atKnownFiles.items():
                env.Depends(
                    target,
                    env.File(strPath)
                )
                env.Depends(
                    target,
                    SCons.Node.Python.Value(
                        'KNOWN_FILE:%s:%s' %
                        (strId, strPath))
                )

    if 'APPIMAGE_INCLUDE_PATHS' in env:
        astrIncludePaths = env['APPIMAGE_INCLUDE_PATHS']
        if astrIncludePaths is not None and len(astrIncludePaths) != 0:
            env.Depends(
                target,
                SCons.Node.Python.Value(
                    'INCLUDE_PATH:' + ':'.join(astrIncludePaths)
                )
            )

    if 'APPIMAGE_KEYROM_XML' in env:
        strKeyRomPath = env['APPIMAGE_KEYROM_XML']
        if strKeyRomPath is not None and len(strKeyRomPath) != 0:
            env.Depends(
                target,
                env.File(strKeyRomPath)
            )

    fVerbose = False
    if 'APPIMAGE_VERBOSE' in env:
        fVerbose = bool(env['APPIMAGE_VERBOSE'])
    env.Depends(target, SCons.Node.Python.Value(str(fVerbose)))

    return target, source


def __app_image_string(target, source, env):
    return 'AppImage %s' % target[0].get_path()


# ---------------------------------------------------------------------------
#
# Add AppImage builder.
#
def ApplyToEnv(env):
    env['APPIMAGE_KNOWN_FILES'] = None
    env['APPIMAGE_INCLUDE_PATHS'] = None
    env['APPIMAGE_VERBOSE'] = False
    env['APPIMAGE_KEYROM_XML'] = None

    app_image_act = SCons.Action.Action(
        __app_image_action,
        __app_image_string
    )
    app_image_bld = SCons.Script.Builder(
        action=app_image_act,
        emitter=__app_image_emitter,
        suffix='.xml',
        single_source=1)
    env['BUILDERS']['AppImage'] = app_image_bld


if __name__ == '__main__':
    tParser = argparse.ArgumentParser(
        description='Translate an XML APP image description file.'
    )
    tParser.add_argument(
        'strInputFile',
        metavar='INPUT_FILE',
        help='read the XML data from INPUT_FILE'
    )
    tParser.add_argument(
        'astrOutputFiles',
        nargs='+',
        metavar='OUTPUT_FILE',
        help='write the output to OUTPUT_FILE'
    )
    tParser.add_argument(
        '-n', '--netx-type',
        dest='strNetxType',
        required=True,
        choices=[
            # For compatibility with hboot_image.py
            # 'NETX90',
            # 'NETX90B',
            # 'NETX90_MPW',
            # For compatibility with HWConfig tool
            'netx90',  # Alias for the latest chip revision, currently rev. 1
            'netx90_mpw',
            'netx90_rev0',
            'netx90_rev1',
        ],
        metavar='NETX',
        help='Build the image for netx type NETX.'
    )
    tParser.add_argument(
        '-c', '--objcopy',
        dest='strObjCopy',
        required=False,
        default='objcopy',
        metavar='FILE',
        help='Use FILE as the objcopy tool.'
    )
    tParser.add_argument(
        '-d', '--objdump',
        dest='strObjDump',
        required=False,
        default='objdump',
        metavar='FILE',
        help='Use FILE as the objdump tool.'
    )
    tParser.add_argument(
        '-r', '--readelf',
        dest='strReadElf',
        required=False,
        default='readelf',
        metavar='FILE',
        help='Use FILE as the readelf tool.'
    )
    tParser.add_argument(
        '-A', '--alias',
        dest='astrAliases',
        required=False,
        action='append',
        metavar='ALIAS=FILE',
        help='Add an alias in the form ALIAS=FILE.'
    )
    tParser.add_argument(
        '-I', '--include',
        dest='astrIncludePaths',
        required=False,
        action='append',
        metavar='PATH',
        help='Add PATH to the list of include paths.'
    )
    tParser.add_argument(
        '-k', '--keyrom',
        dest='strKeyRomPath',
        required=False,
        default=None,
        metavar='FILE',
        help='Read the keyrom data from FILE.'
    )
    tParser.add_argument(
        '-s',
        '--sdram_split_offset',
        dest='strSDRamSplitOffset',
        default="0x00000000",
        required=False,
        metavar="SDRAM",
        help='Address offset for COM CPU to access APP side SDRAM.'
    )
    tParser.add_argument(
        '-v',
        '--verbose',
        dest='fVerbose',
        action='store_true',
        default=False,
        help='be verbose'
    )
    tArgs = tParser.parse_args()

    # Use a default logging level of "WARNING". Change it to "DEBUG" in
    # verbose mode.
    tLoggingLevel = logging.WARNING
    if tArgs.fVerbose is True:
        tLoggingLevel = logging.DEBUG
    logging.basicConfig(level=tLoggingLevel)

    # Parse all alias definitions.
    atKnownFiles = {}
    if tArgs.astrAliases is not None:
        tPattern = re.compile('([a-zA-Z0-9_]+)=(.*)$')
        for strAliasDefinition in tArgs.astrAliases:
            tMatch = re.match(tPattern, strAliasDefinition)
            if tMatch is None:
                raise Exception(
                    'Invalid alias definition: "%s". '
                    'It must be "ALIAS=FILE" instead.' % strAliasDefinition
                )
            strAlias = tMatch.group(1)
            strFile = tMatch.group(2)
            if strAlias in atKnownFiles:
                raise Exception(
                    'Double defined alias "%s". The old value "%s" should be '
                    'overwritten with "%s".' % (
                        strAlias,
                        atKnownFiles[strAlias],
                        strFile
                    )
                )
            atKnownFiles[strAlias] = strFile

    # Set an empty list of include paths if nothing was specified.
    if tArgs.astrIncludePaths is None:
        tArgs.astrIncludePaths = []

    tEnv = {
        'OBJCOPY': tArgs.strObjCopy,
        'OBJDUMP': tArgs.strObjDump,
        'READELF': tArgs.strReadElf,
        'HBOOT_INCLUDE': tArgs.astrIncludePaths
    }

    ulSDRamSplitOffset = int(tArgs.strSDRamSplitOffset, 0)
    tAppImg = AppImage(tEnv, tArgs.strNetxType, tArgs.astrIncludePaths, atKnownFiles, ulSDRamSplitOffset)
    if tArgs.strKeyRomPath is not None:
        tAppImg.read_keyrom(tArgs.strKeyRomPath)

    #print ("===================================")
    #print ("Number of destination paths: %d" % (len(tArgs.astrOutputFiles)))
    #for strDesinationPath in tArgs.astrOutputFiles:
    #    print('>%s<' % strDesinationPath)
    #print ("===================================")

    tAppImg.process_app_image(
        tArgs.strInputFile,
        tArgs.astrOutputFiles
    )
