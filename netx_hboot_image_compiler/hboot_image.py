# -*- coding: utf-8 -*-

import array
import ast
import base64
import binascii
import hashlib
import math
import os
import os.path
import re
import string
import subprocess
import tempfile
import xml.dom.minidom
import xml.etree.ElementTree

from . import elf_support
from . import option_compiler
from . import patch_definitions
from . import snippet_library


class ResolveDefines(ast.NodeTransformer):
    __atDefines = None

    def setDefines(self, atDefines):
        self.__atDefines = atDefines

    def visit_Name(self, node):
        tNode = None
        strName = node.id
        if strName in self.__atDefines:
            tValue = self.__atDefines[strName]
            # Check for a set of base types.
            tValueNode = None
            if type(tValue) is int:
                tValueNode = ast.Num(n=tValue)
            elif type(tValue) is str:
                tValueNode = ast.Str(s=tValue)
            else:
                raise Exception(
                    'Not implemented type for "%s": %s' % (
                        strName,
                        str(type(tValue))
                    )
                )
            tNode = ast.copy_location(tValueNode, node)
        else:
            raise Exception('Unknown constant "%s".' % node.id)
        return tNode


class HbootImage:
    __fVerbose = False

    # This is the list of override items for the header.
    __atHeaderOverride = None

    # This is a list with all chunks.
    __atChunkData = None

    # This is the environment.
    __tEnv = None

    # This is a list of all include paths.
    __astrIncludePaths = None

    # This is a dictionary of all resolved files.
    __atKnownFiles = None

    # This is a dictionary of key/value pairs to do replacements with.
    __atGlobalDefines = None

    __cPatchDefinitions = None

    __cSnippetLibrary = None

    __astrDependencies = None

    __strNetxType = None
    __tImageType = None
    __fHasHeader = None
    __fHasEndMarker = None
    __astrToImageType = None
    __IMAGE_TYPE_REGULAR = 0
    __IMAGE_TYPE_INTRAM = 1
    __IMAGE_TYPE_SECMEM = 2
    __IMAGE_TYPE_COM_INFO_PAGE = 3
    __IMAGE_TYPE_APP_INFO_PAGE = 4
    __IMAGE_TYPE_ALTERNATIVE = 5
    __sizHashDw = None

    __XmlKeyromContents = None
    __cfg_openssl = 'openssl'
    __cfg_openssloptions = None

    # This is the revision for the netX10, netX51 and netX52 Secmem zone.
    __SECMEM_ZONE2_REV1_0 = 0x81

    # The magic cookies for the different chips.
    __MAGIC_COOKIE_NETX56 = 0xf8beaf00
    __MAGIC_COOKIE_NETX4000 = 0xf3beaf00
    __MAGIC_COOKIE_NETX4000_ALT = 0xf3ad9e00
    __MAGIC_COOKIE_NETX90_MPW = 0xf3beaf00
    __MAGIC_COOKIE_NETX90_MPW_ALT = 0xf3ad9e00
    __MAGIC_COOKIE_NETX90 = 0xf3beaf00
    __MAGIC_COOKIE_NETX90_ALT = 0xf3ad9e00
    __MAGIC_COOKIE_NETX90B = 0xf3beaf00
    __MAGIC_COOKIE_NETX90B_ALT = 0xf3ad9e00

    __resolver = None

    __ulStartOffset = 0

    __strDevice = None

    __fMoreChunksAllowed = None

    __ulPaddingPreSize = None
    __ucPaddingPreValue = None

    def __init__(self, tEnv, strNetxType, **kwargs):
        strPatchDefinition = None
        strKeyromFile = None
        astrIncludePaths = []
        astrSnippetSearchPaths = []
        atKnownFiles = {}
        atGlobalDefines = {}
        atOpensslOptions = []
        fVerbose = False

        # Parse the kwargs.
        for strKey, tValue in iter(list(kwargs.items())):
            if strKey == 'patch_definition':
                strPatchDefinition = tValue

            elif strKey == 'keyrom':
                strKeyromFile = tValue

            elif strKey == 'sniplibs':
                if tValue is None:
                    pass
                elif isinstance(tValue, ("".__class__, "".__class__)):
                    astrSnippetSearchPaths.append(tValue)
                else:
                    astrSnippetSearchPaths.extend(tValue)

            elif strKey == 'includes':
                if tValue is None:
                    pass
                elif isinstance(tValue, ("".__class__, "".__class__)):
                    astrIncludePaths.append(tValue)
                else:
                    astrIncludePaths.extend(tValue)

            elif strKey == 'known_files':
                if tValue is None:
                    pass
                else:
                    atKnownFiles.update(tValue)

            elif strKey == 'verbose':
                fVerbose = bool(tValue)

            elif strKey == 'defines':
                atGlobalDefines = dict(tValue)

            elif strKey == 'openssloptions':
                atOpensslOptions = tValue

        # Set the default search path if nothing was specified.
        if len(astrSnippetSearchPaths) == 0:
            astrSnippetSearchPaths = ['sniplib']

        self.__fVerbose = fVerbose

        # Do not override anything in the pre-calculated header yet.
        self.__atHeaderOverride = [None] * 16

        # Add info to be used by the flasher to the header of the boot image.
        self.__fSetFlasherParameters = False

        # No chunks yet.
        self.__atChunkData = None

        # Set the environment.
        self.__tEnv = tEnv

        # Set the known files.
        self.__atKnownFiles = atKnownFiles

        # Set the defines.
        self.__atGlobalDefines = atGlobalDefines

        # Set the OpenSSL options.
        self.__cfg_openssloptions = atOpensslOptions

        if self.__fVerbose:
            print('[HBootImage] Configuration: netX type = %s' % strNetxType)
            print('[HBootImage] Configuration: patch definitions = "%s"' %
                  strPatchDefinition)
            print('[HBootImage] Configuration: Keyrom = "%s"' %
                  str(strKeyromFile))

            if len(astrSnippetSearchPaths) == 0:
                print('[HBootImage] Configuration: No Sniplibs.')
            else:
                for strPath in astrSnippetSearchPaths:
                    print('[HBootImage] Configuration: Sniplib at "%s"' %
                          strPath)

            if len(astrIncludePaths) == 0:
                print('[HBootImage] Configuration: No include paths.')
            else:
                for strPath in astrIncludePaths:
                    print('[HBootImage] Configuration: Include path "%s"' %
                          strPath)

            if len(atKnownFiles) == 0:
                print('[HBootImage] Configuration: No known files.')
            else:
                for strKey, strPath in atKnownFiles.items():
                    print(
                        '[HBootImage] Configuration: '
                        'Known file "%s" at "%s".' % (
                            strKey,
                            strPath
                        )
                    )

            if len(atGlobalDefines) == 0:
                print('[HBootImage] Configuration: No defines.')
            else:
                for strKey, strValue in atGlobalDefines.items():
                    print(
                        '[HBootImage] Configuration: '
                        'Define %s=%s' % (
                            strKey,
                            strValue
                        )
                    )

        if strPatchDefinition is not None:
            self.__cPatchDefinitions = patch_definitions.PatchDefinitions()
            self.__cPatchDefinitions.read_patch_definition(strPatchDefinition)

        # use in memory sqlite database to avoid problems with concurrent builds
        #self.__cSnippetLibrary = snippet_library.SnippetLibrary(
        #    '.sniplib.dblite',
        #    astrSnippetSearchPaths,
        #    debug=self.__fVerbose
        #)
        self.__cSnippetLibrary = snippet_library.SnippetLibrary(':memory:', astrSnippetSearchPaths, debug=self.__fVerbose)


        self.__strNetxType = strNetxType
        self.__tImageType = None
        self.__sizHashDw = None

        self.__astrToImageType = dict({
            'REGULAR': self.__IMAGE_TYPE_REGULAR,
            'INTRAM': self.__IMAGE_TYPE_INTRAM,
            'SECMEM': self.__IMAGE_TYPE_SECMEM,
            'COM_INFO_PAGE': self.__IMAGE_TYPE_COM_INFO_PAGE,
            'APP_INFO_PAGE': self.__IMAGE_TYPE_APP_INFO_PAGE,
            'ALTERNATIVE': self.__IMAGE_TYPE_ALTERNATIVE
        })

        # Initialize the include paths from the environment.
        self.__astrIncludePaths = astrIncludePaths

        # Read the keyrom file if specified.
        if strKeyromFile is not None:
            if self.__fVerbose:
                print('[HBootImage] Init: Reading key ROM file "%s".' %
                      strKeyromFile)
            # Parse the XML file.
            tFile = open(strKeyromFile, 'rt')
            strXml = tFile.read()
            tFile.close()
            self.__XmlKeyromContents = xml.etree.ElementTree.fromstring(strXml)

        self.__resolver = ResolveDefines()

    def __get_tag_id(self, cId0, cId1, cId2, cId3):
        # Combine the 4 ID characters to a 32 bit value.
        ulId = (
            ord(cId0) |
            (ord(cId1) << 8) |
            (ord(cId2) << 16) |
            (ord(cId3) << 24)
        )
        return ulId

    def __xml_get_all_text(self, tNode):
        astrText = []
        for tChild in tNode.childNodes:
            if(
                (tChild.nodeType == tChild.TEXT_NODE) or
                (tChild.nodeType == tChild.CDATA_SECTION_NODE)
            ):
                astrText.append(str(tChild.data))
        return ''.join(astrText)

    def __parse_re_match(self, tMatch):
        strExpression = tMatch.group(1)
        tAstNode = ast.parse(strExpression, mode='eval')
        tAstResolved = self.__resolver.visit(tAstNode)
        tResult = eval(compile(tAstResolved, 'lala', mode='eval'))
        if tResult is None:
            raise Exception('Invalid expression: "%s"' % strExpression)
        return tResult

    def __plaintext_to_xml_with_replace(
        self,
        strPlaintext,
        atReplace,
        fIsStandalone
    ):
        # Set all key/value pairs in the local resolver.
        self.__resolver.setDefines(atReplace)

        # Replace all parameter in the snippet.
        strText = re.sub(r'%%(.+?)%%', self.__parse_re_match, strPlaintext)

        # Parse the text as XML.
        tResult = None
        if fIsStandalone is True:
            tXml = xml.dom.minidom.parseString(strText)
            tResult = tXml
        else:
            tXml = xml.dom.minidom.parseString(
                '<?xml version="1.0" encoding="utf-8"?><Root>%s</Root>' %
                strText
            )
            tResult = tXml.documentElement
        return tResult

    def __preprocess_snip(self, tSnipNode):
        # Get the group, artifact and optional revision.
        strGroup = tSnipNode.getAttribute('group')
        if len(strGroup) == 0:
            raise Exception(
                'The "group" attribute of a "Snip" node must not be empty.'
            )
        strArtifact = tSnipNode.getAttribute('artifact')
        if len(strArtifact) == 0:
            raise Exception(
                'The "artifact" attribute of a "Snip" node must not be empty.'
            )
        strVersion = tSnipNode.getAttribute('version')
        if len(strVersion) == 0:
            raise Exception(
                'The "version" attribute of a "Snip" node must not be empty.'
            )

        # Get the name of the snippets for messages.
        strSnipName = 'G="%s",A="%s",V="%s"' % (
            strGroup,
            strArtifact,
            strVersion
        )

        # Get the parameter.
        atParameter = {}
        for tChildNode in tSnipNode.childNodes:
            if tChildNode.nodeType == tChildNode.ELEMENT_NODE:
                strTag = tChildNode.localName
                if strTag == 'Parameter':
                    # Get the "name" attribute.
                    strName = tChildNode.getAttribute('name')
                    if len(strName) == 0:
                        raise Exception(
                            'Snippet %s instanciation failed: a parameter '
                            'node is missing the "name" attribute!' %
                            strSnipName
                        )
                    # Get the value.
                    strValue = self.__xml_get_all_text(tChildNode)
                    # Was the parameter already defined?
                    if strName in atParameter:
                        raise Exception(
                            'Snippet %s instanciation failed: parameter "%s" '
                            'is defined more than once!' % (
                                strSnipName,
                                strName
                            )
                        )
                    else:
                        atParameter[strName] = strValue
                else:
                    raise Exception(
                        'Snippet %s instanciation failed: unknown tag "%s" '
                        'found!' % (
                            strSnipName,
                            strTag
                        )
                    )

        # Search the snippet.
        tSnippetAttr = self.__cSnippetLibrary.find(
            strGroup,
            strArtifact,
            strVersion,
            atParameter
        )
        strSnippetText = tSnippetAttr[0]
        if strSnippetText is None:
            raise Exception('Snippet not found!')

        # Get the list of key/value pairs for the replacement.
        atReplace = {}
        atReplace.update(self.__atGlobalDefines)
        atReplace.update(tSnippetAttr[1])

        # Replace and convert to XML.
        tSnippetNode = self.__plaintext_to_xml_with_replace(
            strSnippetText,
            atReplace,
            False
        )

        # Add the snippet file to the dependencies.
        strSnippetAbsFile = tSnippetAttr[2]
        if strSnippetAbsFile not in self.__astrDependencies:
            self.__astrDependencies.append(strSnippetAbsFile)

        # Get the parent node of the "Snip" node.
        tParentNode = tSnipNode.parentNode

        # Replace the "Snip" node with the snippet contents.
        for tNode in tSnippetNode.childNodes:
            tClonedNode = tNode.cloneNode(True)
            tParentNode.insertBefore(tClonedNode, tSnipNode)

        # Remove the old "Snip" node.
        tParentNode.removeChild(tSnipNode)

    def __preprocess_include(self, tIncludeNode):
        # Get the name.
        strIncludeName = tIncludeNode.getAttribute('name')
        if strIncludeName is None:
            raise Exception('The "Include" node has no "name" attribute.')
        if len(strIncludeName) == 0:
            raise Exception('The "name" attribute of an "Include" node must '
                            'not be empty.')

        # Get the parameter.
        atParameter = {}
        for tChildNode in tIncludeNode.childNodes:
            if tChildNode.nodeType == tChildNode.ELEMENT_NODE:
                strTag = tChildNode.localName
                if strTag == 'Parameter':
                    # Get the "name" attribute.
                    strName = tChildNode.getAttribute('name')
                    if len(strName) == 0:
                        raise Exception('Include failed: a parameter node is '
                                        'missing the "name" attribute!')
                    # Get the value.
                    strValue = self.__xml_get_all_text(tChildNode)
                    # Was the parameter already defined?
                    if strName in atParameter:
                        raise Exception('Include failed: parameter "%s" is '
                                        'defined more than once!' %
                                        strIncludeName)
                    else:
                        atParameter[strName] = strValue
                else:
                    raise Exception('Include failed: unknown tag "%s" '
                                    'found!' % strTag)

        # Search the file in the current path and all include paths.
        strAbsIncludeName = self.__find_file(strIncludeName)
        if strAbsIncludeName is None:
            raise Exception('Failed to include file "%s": file not found.' %
                            strIncludeName)

        # Read the complete file as text.
        tFile = open(strAbsIncludeName, 'rt')
        strFileContents = tFile.read()
        tFile.close()

        # Replace and convert to XML.
        atReplace = {}
        atReplace.update(self.__atGlobalDefines)
        atReplace.update(atParameter)
        tNewNode = self.__plaintext_to_xml_with_replace(
            strFileContents,
            atReplace,
            False
        )

        # Add the include file to the dependencies.
        if strAbsIncludeName not in self.__astrDependencies:
            self.__astrDependencies.append(strAbsIncludeName)

        # Get the parent node of the "Include" node.
        tParentNode = tIncludeNode.parentNode

        # Replace the "Include" node with the include file contents.
        for tNode in tNewNode.childNodes:
            tClonedNode = tNode.cloneNode(True)
            tParentNode.insertBefore(tClonedNode, tIncludeNode)

        # Remove the old "Include" node.
        tParentNode.removeChild(tIncludeNode)

    def __preprocess(self, tXmlDocument):
        if self.__strNetxType == 'NETX90_MPW':
            # The netX90 MPW does not have a 'StartAPP' function yet.
            # Replace it with a snippet.
            atNodes = tXmlDocument.getElementsByTagName('StartAPP')
            for tReplaceNode in atNodes:
                strNewText = (
                    '<Snip artifact="start_app_cpu_netx90_mpw" '
                    'group="org.muhkuh.hboot.sniplib" '
                    'version="1.0.0"/>'
                )
                tNewXml = xml.dom.minidom.parseString(
                    '<?xml version="1.0" encoding="utf-8"?><Root>%s</Root>' %
                    strNewText
                )
                tParentNode = tReplaceNode.parentNode
                for tChildNode in tNewXml.documentElement.childNodes:
                    tClonedNode = tChildNode.cloneNode(True)
                    tParentNode.insertBefore(tClonedNode, tReplaceNode)
                # Remove the old "StartAPP" node.
                tParentNode.removeChild(tReplaceNode)

        # Look for all 'Snip' nodes repeatedly until the maximum count is
        # reached or no more 'Snip' nodes are found.
        uiMaximumDepth = 100
        uiDepth = 0
        fFoundPreproc = True
        while fFoundPreproc is True:
            atSnipNodes = tXmlDocument.getElementsByTagName('Snip')
            atIncludeNodes = tXmlDocument.getElementsByTagName('Include')
            if (len(atSnipNodes) == 0) and (len(atIncludeNodes) == 0):
                fFoundPreproc = False
            elif uiDepth >= uiMaximumDepth:
                raise Exception(
                    'Too many nested preprocessor directives found! '
                    'The maximum nesting depth is %d.' % uiMaximumDepth
                )
            else:
                uiDepth += 1
                for tNode in atSnipNodes:
                    self.__preprocess_snip(tNode)
                for tNode in atIncludeNodes:
                    self.__preprocess_include(tNode)


    BUS_SPI = 1
    BUS_IFlash = 2
    atDeviceMapping_netx4000 = {
        'SQIROM0':{'bus':BUS_SPI, 'unit':0, 'chip_select':0},
        'SQIROM1':{'bus':BUS_SPI, 'unit':1, 'chip_select':0},
        }

    atDeviceMapping_netx90 = {
        'INTFLASH':{'bus':BUS_IFlash, 'unit':3, 'chip_select':0},
        'SQIROM':  {'bus':BUS_SPI,    'unit':0, 'chip_select':0},
        }

    ROMLOADER_CHIPTYP_NETX4000_RELAXED     = 8
    ROMLOADER_CHIPTYP_NETX90_MPW           = 10
    ROMLOADER_CHIPTYP_NETX4000_FULL        = 11
    ROMLOADER_CHIPTYP_NETX4100_SMALL       = 12
    ROMLOADER_CHIPTYP_NETX90               = 13
    ROMLOADER_CHIPTYP_NETX90B              = 14

    atChipTypeMapping = {
        'NETX90':           { 'chip_type':ROMLOADER_CHIPTYP_NETX90,            'dev_mapping':atDeviceMapping_netx90},
        'NETX90B':          { 'chip_type':ROMLOADER_CHIPTYP_NETX90B,           'dev_mapping':atDeviceMapping_netx90},
        'NETX90_MPW':       { 'chip_type':ROMLOADER_CHIPTYP_NETX90_MPW,        'dev_mapping':atDeviceMapping_netx90},
        'NETX4000_RELAXED': { 'chip_type':ROMLOADER_CHIPTYP_NETX4000_RELAXED,  'dev_mapping':atDeviceMapping_netx4000},
        'NETX4000':         { 'chip_type':ROMLOADER_CHIPTYP_NETX4000_FULL,     'dev_mapping':atDeviceMapping_netx4000},
        'NETX4100':         { 'chip_type':ROMLOADER_CHIPTYP_NETX4100_SMALL,    'dev_mapping':atDeviceMapping_netx4000},
    }

    # Insert information for use by the flasher:
    # chip type, target flash device and flash offset.
    #
    # __strNetxType   is always set (mandatory command line arg), but may not be in the mapping.
    # __strDevice     is always set, but may not be in the mapping.
    # __ulStartOffset is always set and defaults to 0.
    #
    # This function is only called if selected by <Header set_flasher_parameters="true">
    # -> Raise an error if the information can't be determined.
    def __set_flasher_parameters(self, aBootBlock):
        if self.__strNetxType not in self.atChipTypeMapping:
            raise Exception("Cannot set flasher parameters for chip type %s" % self.__strNetxType)
        tChipMap = self.atChipTypeMapping[self.__strNetxType]
        ucChiptype = tChipMap['chip_type']
        tDevMap = tChipMap['dev_mapping']
        if self.__strDevice not in tDevMap:
            raise Exception ("Cannot set flasher parameters for device %s" % self.__strDevice)
        tDevInfo = tDevMap[self.__strDevice]

        ulFlashInfo = 1 * ucChiptype + 0x100 * tDevInfo['bus'] + 0x10000 * tDevInfo['unit'] + 0x1000000 * tDevInfo['chip_select']
        ulFlashOffset = self.__ulStartOffset

        aBootBlock[5] = ulFlashInfo
        aBootBlock[2] = ulFlashOffset


    def __build_standard_header(self, atChunks):

        ulMagicCookie = None
        ulSignature = None
        if self.__strNetxType == 'NETX56':
            ulMagicCookie = self.__MAGIC_COOKIE_NETX56
            ulSignature = self.__get_tag_id('M', 'O', 'O', 'H')
        elif(
            (self.__strNetxType == 'NETX4000_RELAXED') or
            (self.__strNetxType == 'NETX4000') or
            (self.__strNetxType == 'NETX4100')
        ):
            if self.__tImageType == self.__IMAGE_TYPE_ALTERNATIVE:
                ulMagicCookie = self.__MAGIC_COOKIE_NETX4000_ALT
            else:
                ulMagicCookie = self.__MAGIC_COOKIE_NETX4000
            ulSignature = self.__get_tag_id('M', 'O', 'O', 'H')
        elif self.__strNetxType == 'NETX90_MPW':
            ulMagicCookie = self.__MAGIC_COOKIE_NETX90_MPW
            ulSignature = self.__get_tag_id('M', 'O', 'O', 'H')
        elif self.__strNetxType == 'NETX90':
            if self.__tImageType == self.__IMAGE_TYPE_ALTERNATIVE:
                ulMagicCookie = self.__MAGIC_COOKIE_NETX90_ALT
            else:
                ulMagicCookie = self.__MAGIC_COOKIE_NETX90
            ulSignature = self.__get_tag_id('M', 'O', 'O', 'H')
        elif self.__strNetxType == 'NETX90B':
            if self.__tImageType == self.__IMAGE_TYPE_ALTERNATIVE:
                ulMagicCookie = self.__MAGIC_COOKIE_NETX90B_ALT
            else:
                ulMagicCookie = self.__MAGIC_COOKIE_NETX90B
            ulSignature = self.__get_tag_id('M', 'O', 'O', 'H')
        else:
            raise Exception(
                'Missing platform configuration: no standard header '
                'configured, please update the HBOOT image compiler.'
            )

        # Get the hash for the image.
        tHash = hashlib.sha224()
        tHash.update(atChunks.tobytes())
        aulHash = array.array('I', tHash.digest())

        # Get the parameter0 value.
        # For now only the lower 4 bits are defined. They set the number of
        # hash DWORDs minus 1.
        ulParameter0 = self.__sizHashDw - 1

        # Build the boot block.
        aBootBlock = array.array('I', [0] * 16)
        aBootBlock[0x00] = ulMagicCookie        # Magic cookie.
        aBootBlock[0x01] = 0                    # reserved
        aBootBlock[0x02] = 0                    # reserved
        aBootBlock[0x03] = 0                    # reserved
        aBootBlock[0x04] = len(atChunks)        # chunks dword size
        aBootBlock[0x05] = 0                    # reserved
        aBootBlock[0x06] = ulSignature          # The image signature.
        aBootBlock[0x07] = ulParameter0         # Image parameters.
        aBootBlock[0x08] = aulHash[0]           # chunks hash
        aBootBlock[0x09] = aulHash[1]           # chunks hash
        aBootBlock[0x0a] = aulHash[2]           # chunks hash
        aBootBlock[0x0b] = aulHash[3]           # chunks hash
        aBootBlock[0x0c] = aulHash[4]           # chunks hash
        aBootBlock[0x0d] = aulHash[5]           # chunks hash
        aBootBlock[0x0e] = aulHash[6]           # chunks hash
        aBootBlock[0x0f] = 0x00000000           # simple header checksum

        return aBootBlock

    def __combine_headers(self, atHeaderStandard):
        """ Combine the override elements with the standard header """
        aCombinedHeader = array.array('I', [0] * 16)

        ulBootblockChecksum = 0
        for iCnt in range(0, 15):
            if self.__atHeaderOverride[iCnt] is None:
                ulData = atHeaderStandard[iCnt]
            else:
                ulData = self.__atHeaderOverride[iCnt]
            aCombinedHeader[iCnt] = ulData
            ulBootblockChecksum += ulData
            ulBootblockChecksum &= 0xffffffff
        ulBootblockChecksum = (ulBootblockChecksum - 1) ^ 0xffffffff

        # Does an override element exist for the checksum?
        if self.__atHeaderOverride[0x0f] is None:
            ulData = ulBootblockChecksum
        else:
            # Override the checksum.
            ulData = self.__atHeaderOverride[0x0f]
        aCombinedHeader[0x0f] = ulData

        return aCombinedHeader

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

    def __add_array_with_fillup(self, aucBuffer, aucNewData, sizMinimum):
        aucBuffer.extend(aucNewData)
        sizNewData = len(aucNewData)
        if sizNewData < sizMinimum:
            aucBuffer.extend([0] * (sizMinimum - sizNewData))

    def __parse_numeric_expression(self, strExpression):
        tAstNode = ast.parse(strExpression, mode='eval')
        tAstResolved = self.__cPatchDefinitions.resolve_constants(tAstNode)
        ulResult = eval(compile(tAstResolved, 'lala', mode='eval'))
        # TODO: is this really necessary? Maybe ast.literal_eval throws
        # something already.
        if ulResult is None:
            raise Exception('Invalid number: "%s"' % strExpression)
        return ulResult

    def __parse_header_options(self, tOptionsNode):
        strFlashInfo = tOptionsNode.getAttribute('set_flasher_parameters')
        if strFlashInfo == "":
            self.__fSetFlasherParameters = False
        elif strFlashInfo == "true":
            self.__fSetFlasherParameters = True
        elif strFlashInfo == "false":
            self.__fSetFlasherParameters = False
        else:
            raise Exception("Incorrect value of <Header> attribute 'set_flasher_parameters': %s" % strFlashInfo)


        # Loop over all child nodes.
        for tValueNode in tOptionsNode.childNodes:
            if tValueNode.nodeType == tValueNode.ELEMENT_NODE:
                if tValueNode.localName == 'Value':
                    # Found a value node. It must have an index attribute which
                    # evaluates to a number between 0 and 15.
                    strIndex = tValueNode.getAttribute('index')
                    if len(strIndex) == 0:
                        raise Exception(
                            'The Value node has no index attribute!'
                        )
                    ulIndex = self.__parse_numeric_expression(strIndex)

                    # The index must be >=0 and <16.
                    if (ulIndex < 0) or (ulIndex > 15):
                        raise Exception(
                            'The index exceeds the valid range '
                            'of [0..15]: %d' % ulIndex
                        )

                    # Get the data.
                    strData = self.__xml_get_all_text(tValueNode)
                    if len(strData) == 0:
                        raise Exception('The Value node has no content!')

                    ulData = self.__parse_numeric_expression(strData)
                    # The data must be an unsigned 32bit number.
                    if (ulData < 0) or (ulIndex > 0xffffffff):
                        raise Exception(
                            'The data exceeds the valid range of an '
                            'unsigned 32bit number: %d' % ulData
                        )

                    # Is the index already modified?
                    if not self.__atHeaderOverride[ulIndex] is None:
                        raise Exception(
                            'The value at index %d is already '
                            'set to 0x%08x!' % (ulIndex, ulData)
                        )

                    # Set the value.
                    self.__atHeaderOverride[ulIndex] = ulData
                else:
                    raise Exception('Unexpected node: %s' %
                                    tValueNode.localName)

    def __append_32bit(self, atData, ulValue):
        atData.append(ulValue & 0xff)
        atData.append((ulValue >> 8) & 0xff)
        atData.append((ulValue >> 16) & 0xff)
        atData.append((ulValue >> 24) & 0xff)

    def __crc16(self, strData):
        usCrc = 0
        for uiCnt in range(0, len(strData)):
            ucByte = ord(strData[uiCnt])
            usCrc = (usCrc >> 8) | ((usCrc & 0xff) << 8)
            usCrc ^= ucByte
            usCrc ^= (usCrc & 0xff) >> 4
            usCrc ^= (usCrc & 0x0f) << 12
            usCrc ^= ((usCrc & 0xff) << 4) << 1
        return usCrc

    def __build_chunk_options(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        atChunk = None

        # Compile the options definition to a string of bytes.
        tOptionCompiler = option_compiler.OptionCompiler(
            self.__cPatchDefinitions
        )
        tOptionCompiler.process(tChunkNode)
        strData = tOptionCompiler.tostring()

        # Return the plain option chunk for SECMEM images.
        # Add a header otherwise.
        if self.__tImageType == self.__IMAGE_TYPE_SECMEM:
            atChunk = array.array('B')
            atChunk.frombytes(strData)
        else:
            if self.__strNetxType == 'NETX56':
                # Pad the option chunk plus a CRC16 to 32 bit size.
                strPadding = bytes((4 - ((len(strData) + 2) % 4)) & 3)
                strChunk = strData + strPadding

                # Get the CRC16 for the chunk.
                usCrc = self.__crc16(strChunk)
                strChunk += chr((usCrc >> 8) & 0xff)
                strChunk += chr(usCrc & 0xff)

                aulData = array.array('I')
                aulData.frombytes(strChunk)

                atChunk = array.array('I')
                atChunk.append(self.__get_tag_id('O', 'P', 'T', 'S'))
                atChunk.append(len(aulData))
                atChunk.extend(aulData)

            elif(
                (self.__strNetxType == 'NETX4000_RELAXED') or
                (self.__strNetxType == 'NETX4000') or
                (self.__strNetxType == 'NETX4100')
            ):
                # Pad the option chunk to 32 bit size.
                strPadding = bytes((4 - (len(strData) % 4)) & 3)
                strChunk = strData + strPadding

                aulData = array.array('I')
                aulData.frombytes(strChunk)

                atChunk = array.array('I')
                atChunk.append(self.__get_tag_id('O', 'P', 'T', 'S'))
                atChunk.append(len(aulData) + self.__sizHashDw)
                atChunk.extend(aulData)

                # Get the hash for the chunk.
                tHash = hashlib.sha384()
                tHash.update(atChunk.tobytes())
                strHash = tHash.digest()
                aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
                atChunk.extend(aulHash)

            elif(
                (self.__strNetxType == 'NETX90_MPW') or
                (self.__strNetxType == 'NETX90') or
                (self.__strNetxType == 'NETX90B')
            ):
                # Pad the option chunk to 32 bit size.
                strPadding = bytes((4 - (len(strData) % 4)) & 3)
                strChunk = strData + strPadding

                aulData = array.array('I')
                aulData.frombytes(strChunk)

                atChunk = array.array('I')
                atChunk.append(self.__get_tag_id('O', 'P', 'T', 'S'))
                atChunk.append(len(aulData) + self.__sizHashDw)
                atChunk.extend(aulData)

                # Get the hash for the chunk.
                tHash = hashlib.sha384()
                tHash.update(atChunk.tobytes())
                strHash = tHash.digest()
                aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
                atChunk.extend(aulHash)

            else:
                raise Exception(
                    '"Opts" chunk is not supported for chip type "%s".' %
                    (self.__strNetxType)
                )

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = atChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __get_data_contents_elf(self, tNode, strAbsFilePath, fWantLoadAddress):
        # Get the segment names to dump. It is a comma separated string.
        # This is optional. If no segment names are specified, all sections
        # with PROGBITS are dumped.
        strSegmentsToDump = tNode.getAttribute('segments').strip()
        astrSegmentsToDump = None
        if len(strSegmentsToDump) != 0:
            astrSegmentsToDump = [
                strSegment.strip() for strSegment in
                strSegmentsToDump.split(',')
            ]

        # Extract the segments.
        atSegments = elf_support.get_segment_table(
            self.__tEnv,
            strAbsFilePath,
            astrSegmentsToDump
        )
        # Get the estimated binary size from the segments.
        ulEstimatedBinSize = elf_support.get_estimated_bin_size(atSegments)
        # Do not create files larger than 512MB.
        if ulEstimatedBinSize >= 0x20000000:
            raise Exception('The resulting file seems to extend '
                            '512MBytes. Too scared to continue!')

        if fWantLoadAddress is True:
            strOverwriteAddress = tNode.getAttribute(
                'overwrite_address'
            ).strip()
            if len(strOverwriteAddress) == 0:
                pulLoadAddress = elf_support.get_load_address(atSegments)
            else:
                pulLoadAddress = int(strOverwriteAddress, 0)
        else:
            pulLoadAddress = None

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
        #subprocess.check_call(astrCmd)

        try:
            subprocess.check_call(astrCmd)
        except Exception as e:
            print("Failed to call external program:")
            print(astrCmd)
            print(e)
            raise


        # Get the application data.
        tBinFile = open(strBinFileName, 'rb')
        strData = tBinFile.read()
        tBinFile.close()

        # Remove the temp file.
        os.remove(strBinFileName)

        return strData, pulLoadAddress

    def __get_data_contents_key(self, tKeyNode):
        strData = None

        if(
            (self.__strNetxType == 'NETX90_MPW') or
            (self.__strNetxType == 'NETX90') or
            (self.__strNetxType == 'NETX90B')
        ):
            aucData = array.array('B')

            atKey = {}
            self.__usip_parse_trusted_path(tKeyNode, atKey)

            iKeyTyp_1ECC_2RSA = atKey['iKeyTyp_1ECC_2RSA']
            atAttr = atKey['atAttr']
            if iKeyTyp_1ECC_2RSA == 2:
                # Add the algorithm.
                aucData.append(iKeyTyp_1ECC_2RSA)
                # Add the strength.
                aucData.append(atAttr['id'])
                # Add the public modulus N and fill up to 64 bytes.
                self.__add_array_with_fillup(aucData, atAttr['mod'], 512)
                # Add the exponent E.
                aucData.extend(atAttr['exp'])

            elif iKeyTyp_1ECC_2RSA == 1:
                # Add the algorithm.
                aucData.append(iKeyTyp_1ECC_2RSA)
                # Add the strength.
                aucData.append(atAttr['id'])
                # Write all fields and fill up to 64 bytes.
                self.__add_array_with_fillup(aucData, atAttr['Qx'], 64)
                self.__add_array_with_fillup(aucData, atAttr['Qy'], 64)
                self.__add_array_with_fillup(aucData, atAttr['a'], 64)
                self.__add_array_with_fillup(aucData, atAttr['b'], 64)
                self.__add_array_with_fillup(aucData, atAttr['p'], 64)
                self.__add_array_with_fillup(aucData, atAttr['Gx'], 64)
                self.__add_array_with_fillup(aucData, atAttr['Gy'], 64)
                self.__add_array_with_fillup(aucData, atAttr['n'], 64)
                aucData.extend([0, 0, 0])

            strData = aucData.tobytes()

        else:
            raise Exception(
                'Key data is not supported for the netX type "%s".' %
                self.__strNetxType
            )

        return strData

    REGI_COMMAND_NoOperation = 0
    REGI_COMMAND_LoadStore = 1
    REGI_COMMAND_Delay = 2
    REGI_COMMAND_Poll = 3
    REGI_COMMAND_LoadStoreMask = 4
    REGI_COMMAND_SourceIsRegister = 0x10
    REGI_COMMAND_UnlockAccessKey = 0x20

    atRegisterCommandTypes = {
        'nop': {
            'atAttributes': [],
            'ucCmd': REGI_COMMAND_NoOperation,
            'atSerialize': [],
        },
        'set': {
            'atAttributes': [
                {'name': 'address', 'type': 'uint32'},
                {'name': 'value',   'type': 'uint32'},
                {'name': 'unlock',  'type': 'bool', 'optional': True, 'default': False}
            ],
            'ucCmd': REGI_COMMAND_LoadStore,
            'atSerialize': ['value', 'address'],
        },
        'copy': {
            'atAttributes': [
                {'name': 'source',  'type': 'uint32'},
                {'name': 'dest',    'type': 'uint32'},
                {'name': 'unlock',  'type': 'bool', 'optional': True, 'default': False}
            ],
            'ucCmd': REGI_COMMAND_LoadStore + REGI_COMMAND_SourceIsRegister,
            'atSerialize': ['source', 'dest'],
        },
        'delay': {
            'atAttributes': [
                {'name': 'time_ms', 'type': 'uint32'}
            ],
            'ucCmd': REGI_COMMAND_Delay,
            'atSerialize': ['time_ms'],
        },
        'poll': {
            'atAttributes': [
                {'name': 'address',     'type': 'uint32'},
                {'name': 'mask',        'type': 'uint32', 'optional': True, 'default': 0xffffffff},
                {'name': 'cmp',         'type': 'uint32'},
                {'name': 'timeout_ms',  'type': 'uint32'},
            ],
            'ucCmd': REGI_COMMAND_Poll,
            'atSerialize': ['address', 'mask', 'cmp', 'timeout_ms'],
        },
        'setmask': {
            'atAttributes': [
                {'name': 'address', 'type': 'uint32'},
                {'name': 'mask', 'type': 'uint32'},
                {'name': 'value',   'type': 'uint32'},
                {'name': 'unlock',  'type': 'bool', 'optional': True, 'default': False}
            ],
            'ucCmd': REGI_COMMAND_LoadStoreMask,
            'atSerialize': ['value', 'mask', 'address'],
        },
        'copymask': {
            'atAttributes': [
                {'name': 'source',  'type': 'uint32'},
                {'name': 'mask', 'type': 'uint32'},
                {'name': 'dest',    'type': 'uint32'},
                {'name': 'unlock',  'type': 'bool', 'optional': True, 'default': False}
            ],
            'ucCmd': REGI_COMMAND_LoadStoreMask + REGI_COMMAND_SourceIsRegister,
            'atSerialize': ['source', 'mask', 'dest'],
        }
    }

    # Read the contents of a <Register> chunk and turn it into an intermediate representation.
    # Attributes not required for a command are ignored, i.e. <nop address="0x10000000" /> is accepted.
    def __get_register_contents(self, tRegNode, atCmd):
        # tRegNode is the <Register> tag. Each child is a register command, e.g. <set>.
        for tCmdNode in tRegNode.childNodes:
            # Is this a node element?
            if tCmdNode.nodeType == tCmdNode.ELEMENT_NODE:
                tCmd = {}
                atCmd.append(tCmd)

                # Get the command name and the list of attributes defined for it.
                strNodeName = tCmdNode.localName
                tCmd['name'] = strNodeName

                if strNodeName not in self.atRegisterCommandTypes:
                    raise Exception(
                        'Unknown command type in register chunk: %s' % (strNodeName)
                    )
                else:
                    atAttribs = self.atRegisterCommandTypes[strNodeName]['atAttributes']

                    # Collect the attributes for the current register command.
                    for tAttrib in atAttribs:
                        # Get name and type of each attribute and whether it's optional.
                        # By default, attributes are mandatory.
                        strAttribName = tAttrib['name']
                        strAttribType = tAttrib['type']
                        fAttribOpt = 'optional' in tAttrib and tAttrib['optional'] is True

                        # Get the value of the XML attribute.
                        # If the attribute is not present, an empty string is returned.
                        strAttribVal = tCmdNode.getAttribute(strAttribName).strip()

                        # The attribute is present. Convert the value.
                        if len(strAttribVal) > 0:
                            if strAttribType == 'uint32':
                                ulAttribVal = self.__parse_numeric_expression(strAttribVal)
                                if ulAttribVal is None:
                                    raise Exception(
                                        'Could not parse value %s in attribute %s' % (strAttribVal, strAttribName)
                                    )
                                tCmd[strAttribName] = ulAttribVal

                            elif strAttribType == 'bool':
                                if strAttribVal == 'true':
                                    tCmd[strAttribName] = True
                                elif strAttribVal == 'false':
                                    tCmd[strAttribName] = False
                                else:
                                    raise Exception(
                                        'Invalid value %s for boolean attribute %s' % (strAttribVal, strAttribName)
                                    )
                            else:
                                tCmd[strAttribName] = strAttribVal

                        # The attribute is not present and it is optional.
                        # Set the default value if defined.
                        elif fAttribOpt:
                            # If optional, get the default value if present.
                            if 'default' in tAttrib:
                                tCmd[strAttribName] = tAttrib['default']

                        # The attribute is not present, but it is mandatory.
                        # Raise an error.
                        else:
                            raise Exception(
                                'Mandatory attribute %s is missing' % (strAttribName)
                            )
                    # print tCmd

    # Serialize the intermediate representation of a Register chunk.
    def __serialize_register_chunk(self, atCmd, aulCmds):
        abData = bytearray()

        for tCmd in atCmd:
            tCmdDesc = self.atRegisterCommandTypes[tCmd['name']]

            ucCmd = tCmdDesc['ucCmd']
            if 'unlock' in tCmd and tCmd['unlock'] is True:
                ucCmd += self.REGI_COMMAND_UnlockAccessKey
            abData.append(ucCmd)

            astrAttribs = tCmdDesc['atSerialize']
            for strAttrib in astrAttribs:
                ulVal = tCmd[strAttrib]
                self.__append_32bit(abData, ulVal)

        # Pad array to multiple of 4 bytes
        while (len(abData) & 3) != 0:
            abData.append(0)

        # Convert to an arrray of dwords
        strData = abData
        aulData = array.array('I')
        aulData.frombytes(strData)

        aulCmds.extend(aulData)

    # Construct a chunk out of chunk data, adding chunk ID, size and hash.
    def __wrap_chunk(self, tChunkAttributes, ulTagId, aulData):
        # Build the chunk.
        aulChunk = array.array('I')
        aulChunk.append(ulTagId)
        aulChunk.append(len(aulData) + self.__sizHashDw)
        aulChunk.extend(aulData)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __build_chunk_register(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tRegNode = tChunkAttributes['tNode']

        # Read the register operations from the XML.
        atCmd = []
        self.__get_register_contents(tRegNode, atCmd)

        # Encode the operations.
        aulData = array.array('I')
        self.__serialize_register_chunk(atCmd, aulData)

        # Build the chunk
        ulTagId = self.__get_tag_id('R', 'E', 'G', 'I')
        self.__wrap_chunk(tChunkAttributes, ulTagId, aulData)


    def __get_firewall_contents(self, tChunkNode, atEntries):
        # Get the data block.
        self.__get_data_contents(tChunkNode, atEntries, False)

    def __serialize_firewall_chunk(self, atEntries, aulData):
        # Convert the padded data to an array.
        strData = atEntries['data']
        if len(strData) != 36*4:
            raise Exception ('The data size of a Firewall chunk must be 36 dwords (144 bytes).')
        aulData.frombytes(strData)

    def __build_chunk_firewall(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # Read the firewall settings from the XML.
        atEntries = {}
        self.__get_firewall_contents(tChunkNode, atEntries)

        # Encode the payload of the firewall chunk.
        aulData = array.array('I')
        self.__serialize_firewall_chunk(atEntries, aulData)

        # Build the chunk
        ulTagId = self.__get_tag_id('F', 'R', 'W', 'L')
        self.__wrap_chunk(tChunkAttributes, ulTagId, aulData)


    def __get_data_contents(self, tDataNode, atData, fWantLoadAddress):
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
                            strAbsFilePath,
                            True
                        )

                    elif strExtension == '.bin':
                        if fWantLoadAddress is True:
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
                    if fWantLoadAddress is True:
                        # Get the address.
                        strAddress = tNode.getAttribute('address')
                        if len(strAddress) == 0:
                            raise Exception('The Hex node has no '
                                            'address attribute!')

                        pulLoadAddress = self.__parse_numeric_expression(
                            strAddress
                        )

                    # Get the text in this node and parse it as hex data.
                    strDataHex = self.__xml_get_all_text(tNode)
                    if strDataHex is None:
                        raise Exception('No text in node "Hex" found!')

                    strDataHex = self.__remove_all_whitespace(strDataHex)
                    strData = binascii.unhexlify(strDataHex)

                elif tNode.localName == 'UInt32':
                    if fWantLoadAddress is True:
                        # Get the address.
                        strAddress = tNode.getAttribute('address')
                        if len(strAddress) == 0:
                            raise Exception('The UInt32 node has no '
                                            'address attribute!')

                        pulLoadAddress = self.__parse_numeric_expression(
                            strAddress
                        )

                    # Get the text in this node and split it by whitespace.
                    strDataUint = self.__xml_get_all_text(tNode)
                    if strDataUint is None:
                        raise Exception('No text in node "UInt32" found!')

                    astrNumbers = strDataUint.split(',')
                    aulNumbers = array.array('I')
                    for strNumber in astrNumbers:
                        ulNum = self.__parse_numeric_expression(
                            strNumber.strip()
                        )
                        aulNumbers.append(ulNum)

                    strData = aulNumbers.tobytes()

                elif tNode.localName == 'UInt16':
                    if fWantLoadAddress is True:
                        # Get the address.
                        strAddress = tNode.getAttribute('address')
                        if len(strAddress) == 0:
                            raise Exception('The UInt16 node has no '
                                            'address attribute!')

                        pulLoadAddress = self.__parse_numeric_expression(
                            strAddress
                        )

                    # Get the text in this node and split it by whitespace.
                    strDataUint = self.__xml_get_all_text(tNode)
                    if strDataUint is None:
                        raise Exception('No text in node "UInt16" found!')

                    astrNumbers = strDataUint.split(',')
                    ausNumbers = array.array('H')
                    for strNumber in astrNumbers:
                        usNum = self.__parse_numeric_expression(
                            strNumber.strip()
                        )
                        ausNumbers.append(usNum)

                    strData = ausNumbers.tobytes()

                elif tNode.localName == 'UInt8':
                    if fWantLoadAddress is True:
                        # Get the address.
                        strAddress = tNode.getAttribute('address')
                        if len(strAddress) == 0:
                            raise Exception('The UInt8 node has no '
                                            'address attribute!')

                        pulLoadAddress = self.__parse_numeric_expression(
                            strAddress
                        )

                    # Get the text in this node and split it by whitespace.
                    strDataUint = self.__xml_get_all_text(tNode)
                    if strDataUint is None:
                        raise Exception('No text in node "UInt8" found!')

                    astrNumbers = strDataUint.split(',')
                    aucNumbers = array.array('B')
                    for strNumber in astrNumbers:
                        ucNum = self.__parse_numeric_expression(
                            strNumber.strip()
                        )
                        aucNumbers.append(ucNum)

                    strData = aucNumbers.tobytes()

                elif tNode.localName == 'Key':
                    if fWantLoadAddress is True:
                        # Get the address.
                        strAddress = tNode.getAttribute('address')
                        if len(strAddress) == 0:
                            raise Exception('The Key node has no '
                                            'address attribute!')

                        pulLoadAddress = self.__parse_numeric_expression(
                            strAddress
                        )
                    strData = self.__get_data_contents_key(tNode)

                elif tNode.localName == 'Concat':
                    if fWantLoadAddress is True:
                        # Get the address.
                        strAddress = tNode.getAttribute('address')
                        if len(strAddress) == 0:
                            raise Exception('The Concat node has no '
                                            'address attribute!')

                        pulLoadAddress = self.__parse_numeric_expression(
                            strAddress
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

                            elif tConcatNode.localName == 'String':
                                # Get the text in this node and include it
                                # verbatim in the chunk.
                                strDataString = self.__xml_get_all_text(
                                    tConcatNode
                                )
                                if strDataString is None:
                                    raise Exception('No text in node "String" '
                                                    ' found!')
                                
                                astrData.append(strDataString.encode('utf-8'))

                            elif tConcatNode.localName == 'UInt32':
                                # Get the text in this node and split it
                                # by whitespace.
                                strDataUint = self.__xml_get_all_text(
                                    tConcatNode
                                )
                                if strDataUint is None:
                                    raise Exception('No text in node '
                                                    '"UInt32" found!')

                                astrNumbers = strDataUint.split(',')
                                aulNumbers = array.array('I')
                                for strNumber in astrNumbers:
                                    ulNum = self.__parse_numeric_expression(
                                        strNumber.strip()
                                    )
                                    aulNumbers.append(ulNum)

                                strDataChunk = aulNumbers.tobytes()
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

                                astrNumbers = strDataUint.split(',')
                                ausNumbers = array.array('H')
                                for strNumber in astrNumbers:
                                    usNum = self.__parse_numeric_expression(
                                        strNumber.strip()
                                    )
                                    ausNumbers.append(usNum)

                                strDataChunk = ausNumbers.tobytes()
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

                                astrNumbers = strDataUint.split(',')
                                aucNumbers = array.array('B')
                                for strNumber in astrNumbers:
                                    ucNum = self.__parse_numeric_expression(
                                        strNumber.strip()
                                    )
                                    aucNumbers.append(ucNum)

                                strDataChunk = aucNumbers.tobytes()
                                astrData.append(strDataChunk)

                            elif tConcatNode.localName == 'Key':
                                strDataChunk = self.__get_data_contents_key(
                                    tConcatNode
                                )
                                astrData.append(strDataChunk)
                                
                            else:
                                raise Exception('Unexpected node: %s' 
                                    % (tConcatNode.localName))
                                    
                    strData = b''.join(astrData)

                else:
                    raise Exception('Unexpected node: %s' % tNode.localName)

        # Check if all parameters are there.
        if strData is None:
            raise Exception('No data specified!')
        if (fWantLoadAddress is True) and (pulLoadAddress is None):
            raise Exception('No load address specified!')

        atData['data'] = strData
        if fWantLoadAddress is True:
            atData['load_address'] = pulLoadAddress

    def __build_chunk_data(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # Get the data block.
        atData = {}
        self.__get_data_contents(tChunkNode, atData, True)
        strData = atData['data']
        pulLoadAddress = atData['load_address']

        # Pad the application size to a multiple of DWORDs.
        strPadding = bytes((4 - (len(strData) % 4)) & 3)
        strChunk = strData + strPadding

        # Convert the padded data to an array.
        aulData = array.array('I')
        aulData.frombytes(strChunk)

        aulChunk = array.array('I')
        # Do not add an ID for info page images.
        if(
            (self.__tImageType != self.__IMAGE_TYPE_COM_INFO_PAGE) and
            (self.__tImageType != self.__IMAGE_TYPE_APP_INFO_PAGE)
        ):
            aulChunk.append(self.__get_tag_id('D', 'A', 'T', 'A'))
            aulChunk.append(len(aulData) + 1 + self.__sizHashDw)
            aulChunk.append(pulLoadAddress)
            aulChunk.extend(aulData)

            # Get the hash for the chunk.
            tHash = hashlib.sha384()
            tHash.update(aulChunk.tobytes())
            strHash = tHash.digest()
            aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
            aulChunk.extend(aulHash)

        else:
            # The info pages only get the data.
            aulChunk = aulData

            # Get the hash for the chunk.
            tHash = hashlib.sha384()
            tHash.update(aulChunk.tobytes())
            strHash = tHash.digest()

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __build_chunk_text(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # Get the text block.
        strText = self.__xml_get_all_text(tChunkNode)

        # Pad the text to a multiple of DWORDs.
        strPadding = chr(0x00) * ((4 - (len(strText) % 4)) & 3)
        strChunk = strText + strPadding

        # Convert the padded text to an array.
        aulData = array.array('I')
        aulData.frombytes(strChunk)

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('T', 'E', 'X', 'T'))
        aulChunk.append(len(aulData) + self.__sizHashDw)
        aulChunk.extend(aulData)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __build_chunk_xip(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # Get the data block.
        atData = {}
        self.__get_data_contents(tChunkNode, atData, True)
        strData = atData['data']
        pulLoadAddress = atData['load_address']

        # Get the available XIP areas for the current platform.
        atXIPAreas = None
        if self.__strNetxType == 'NETX56':
            raise Exception('Continue here!')
        elif(
            (self.__strNetxType == 'NETX4000_RELAXED') or
            (self.__strNetxType == 'NETX4000') or
            (self.__strNetxType == 'NETX4100')
        ):
            atXIPAreas = [
                # SQIROM0
                {
                    'device': 'SQIROM0',
                    'start': 0x10000000,
                    'end': 0x14000000
                },

                # SQIROM1
                {
                    'device': 'SQIROM1',
                    'start': 0x14000000,
                    'end': 0x18000000
                }
            ]
        elif(
            (self.__strNetxType == 'NETX90_MPW') or
            (self.__strNetxType == 'NETX90') or
            (self.__strNetxType == 'NETX90B')
        ):
            atXIPAreas = [
                # SQI flash
                {
                    'device': 'SQIROM',
                    'start': 0x64000000,
                    'end': 0x68000000
                },

                # IFLASH0 and 1
                {
                    'device': 'INTFLASH',
                    'start': 0x00100000,
                    'end': 0x00200000
                }
            ]

        pulXipStartAddress = None
        for tXipArea in atXIPAreas:
            if(
                (pulLoadAddress >= tXipArea['start']) and
                (pulLoadAddress < tXipArea['end'])
            ):
                if tXipArea['device'] != self.__strDevice:
                    raise Exception(
                        'The XIP load address matches the %s device, but the '
                        'image specifies %s' % (
                            tXipArea['device'],
                            self.__strDevice
                        )
                    )
                pulXipStartAddress = tXipArea['start']
                break
        if pulXipStartAddress is None:
            raise Exception(
                'The load address 0x%08x of the XIP block is outside the '
                'available XIP regions of the platform.' % pulLoadAddress
            )

        # Get the requested offset of the data in the XIP area.
        ulOffsetRequested = pulLoadAddress - pulXipStartAddress

        # The requested offset must be the current offset + 8 (4 for the ID
        # and 4 for the length).
        ulOffsetRequestedData = 8

        # Get the current offset in bytes.
        ulOffsetCurrent = atParserState['ulCurrentOffset']

        # The requested offset must be the current offset + the data offset
        ulOffsetCurrentData = ulOffsetCurrent + ulOffsetRequestedData
        if ulOffsetRequested != ulOffsetCurrentData:
            raise Exception(
                'The current offset 0x%08x does not match the requested '
                'offset 0x%08x of the XIP data.' % (
                    ulOffsetCurrentData,
                    ulOffsetRequested
                )
            )

        # The load address must be exactly the address where the code starts.
        # Pad the application size to a multiple of DWORDs.
        strPadding = bytes((4 - (len(strData) % 4)) & 3)
        strChunk = strData + strPadding

        # Convert the padded data to an array.
        aulData = array.array('I')
        aulData.frombytes(strChunk)

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('T', 'E', 'X', 'T'))
        aulChunk.append(len(aulData) + self.__sizHashDw)
        aulChunk.extend(aulData)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __get_execute_data(self, tExecuteNode, atData):
        pfnExecFunction = None
        ulR0 = None
        ulR1 = None
        ulR2 = None
        ulR3 = None

        # Look for a child node named "File".
        for tNode in tExecuteNode.childNodes:
            # Is this a node element?
            if tNode.nodeType == tNode.ELEMENT_NODE:
                # Is this a "File" node?
                if tNode.localName == 'File':
                    # Is there already an exec function?
                    if pfnExecFunction is not None:
                        raise Exception('More than one execution address '
                                        'specified!')

                    # Get the file name.
                    strFileName = tNode.getAttribute('name')
                    if len(strFileName) == 0:
                        raise Exception('The file node has no name attribute!')

                    # Search the file in the current working folder and all
                    # include paths.
                    strAbsFilePath = self.__find_file(strFileName)
                    if strAbsFilePath is None:
                        raise Exception('File %s not found!' % strFileName)

                    # Is this an ELF file?
                    strRoot, strExtension = os.path.splitext(strAbsFilePath)
                    if strExtension != '.elf':
                        raise Exception(
                            'The execute chunk has a file child which points '
                            'to a non-elf file. How to get the execute '
                            'address from this?'
                        )

                    strStartSymbol = tNode.getAttribute('start')
                    if len(strStartSymbol) == 0:
                        strStartSymbol = 'start'

                    # Get all symbols.
                    atSymbols = elf_support.get_symbol_table(self.__tEnv,
                                                             strAbsFilePath)
                    if strStartSymbol not in atSymbols:
                        raise Exception(
                            'The symbol for the start startaddress "%s" '
                            'could not be found!' % strStartSymbol
                        )
                    pfnExecFunction = int(atSymbols[strStartSymbol])
                elif tNode.localName == 'Address':
                    # Is there already an exec function?
                    if pfnExecFunction is not None:
                        raise Exception('More than one execution address '
                                        'specified!')

                    pfnExecFunction = self.__parse_numeric_expression(
                        self.__xml_get_all_text(tNode)
                    )
                elif tNode.localName == 'R0':
                    ulR0 = self.__parse_numeric_expression(
                        self.__xml_get_all_text(tNode)
                    )
                elif tNode.localName == 'R1':
                    ulR1 = self.__parse_numeric_expression(
                        self.__xml_get_all_text(tNode)
                    )
                elif tNode.localName == 'R2':
                    ulR2 = self.__parse_numeric_expression(
                        self.__xml_get_all_text(tNode)
                    )
                elif tNode.localName == 'R3':
                    ulR3 = self.__parse_numeric_expression(
                        self.__xml_get_all_text(tNode)
                    )
                else:
                    raise Exception('Unexpected node: %s' % tNode.localName)

        if pfnExecFunction is None:
            raise Exception('No execution address specified!')
        if ulR0 is None:
            ulR0 = 0
        if ulR1 is None:
            ulR1 = 0
        if ulR2 is None:
            ulR2 = 0
        if ulR3 is None:
            ulR3 = 0

        atData['pfnExecFunction'] = pfnExecFunction
        atData['ulR0'] = ulR0
        atData['ulR1'] = ulR1
        atData['ulR2'] = ulR2
        atData['ulR3'] = ulR3

    def __build_chunk_execute(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        __atData = {
            # The key index must be set by the user.
            'pfnExecFunction': None,
            'ulR0': None,
            'ulR1': None,
            'ulR2': None,
            'ulR3': None
        }
        self.__get_execute_data(tChunkNode, __atData)

        # netX90 and netX90B have some strange additional options.
        ulFlags = None
        sizDataInDwords = 5
        if(
          (self.__strNetxType == 'NETX90') or
          (self.__strNetxType == 'NETX90B')
        ):
            sizDataInDwords = 6

            # Check if the APP CPU should be started.
            fStartAppCpu = False
            strBool = tChunkNode.getAttribute('start_app')
            if len(strBool) != 0:
                fBool = self.__string_to_bool(strBool)
                if fBool is not None:
                    fStartAppCpu = fBool

            # Check if the firewall settings should be locked.
            fLockFirewallSettings = False
            strBool = tChunkNode.getAttribute('lock_firewall')
            if len(strBool) != 0:
                fBool = self.__string_to_bool(strBool)
                if fBool is not None:
                    fLockFirewallSettings = fBool

            # Check if debugging should be activated.
            fActivateDebugging = False
            strBool = tChunkNode.getAttribute('activate_debugging')
            if len(strBool) != 0:
                fBool = self.__string_to_bool(strBool)
                if fBool is not None:
                    fActivateDebugging = fBool

            # Check if the firewall settings should be applied.
            fApplyFirewallSettings = False
            strBool = tChunkNode.getAttribute('apply_firewall_settings')
            if len(strBool) != 0:
                fBool = self.__string_to_bool(strBool)
                if fBool is not None:
                    fApplyFirewallSettings = fBool

            # Combine all flags.
            ulFlags = 0
            if fStartAppCpu is True:
                ulFlags |= 1
            if fLockFirewallSettings is True:
                ulFlags |= 2
            if fActivateDebugging is True:
                ulFlags |= 4
            if fApplyFirewallSettings is True:
                ulFlags |= 8

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('E', 'X', 'E', 'C'))
        aulChunk.append(sizDataInDwords + self.__sizHashDw)
        aulChunk.append(__atData['pfnExecFunction'])
        aulChunk.append(__atData['ulR0'])
        aulChunk.append(__atData['ulR1'])
        aulChunk.append(__atData['ulR2'])
        aulChunk.append(__atData['ulR3'])
        if ulFlags is not None:
            aulChunk.append(ulFlags)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __build_chunk_execute_ca9(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        __atCore0 = {
            # The key index must be set by the user.
            'pfnExecFunction': 0,
            'ulR0': 0,
            'ulR1': 0,
            'ulR2': 0,
            'ulR3': 0
        }
        __atCore1 = {
            # The key index must be set by the user.
            'pfnExecFunction': 0,
            'ulR0': 0,
            'ulR1': 0,
            'ulR2': 0,
            'ulR3': 0
        }

        # Look for a child node named "File".
        for tCoreNode in tChunkNode.childNodes:
            # Is this a node element?
            if tCoreNode.nodeType == tCoreNode.ELEMENT_NODE:
                # Is this a 'Core0' node?
                if tCoreNode.localName == 'Core0':
                    self.__get_execute_data(tCoreNode, __atCore0)

                # Is this a 'Core1' node?
                elif tCoreNode.localName == 'Core1':
                    self.__get_execute_data(tCoreNode, __atCore1)

                else:
                    raise Exception('Unexpected node: %s' %
                                    tCoreNode.localName)

        if(
            (__atCore0['pfnExecFunction'] == 0) and
            (__atCore1['pfnExecFunction'] == 0)
        ):
            print('Warning: No core is started with the ExecuteCA9 chunk!')

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('E', 'X', 'A', '9'))
        aulChunk.append(10 + self.__sizHashDw)
        aulChunk.append(__atCore0['pfnExecFunction'])
        aulChunk.append(__atCore0['ulR0'])
        aulChunk.append(__atCore0['ulR1'])
        aulChunk.append(__atCore0['ulR2'])
        aulChunk.append(__atCore0['ulR3'])
        aulChunk.append(__atCore1['pfnExecFunction'])
        aulChunk.append(__atCore1['ulR0'])
        aulChunk.append(__atCore1['ulR1'])
        aulChunk.append(__atCore1['ulR2'])
        aulChunk.append(__atCore1['ulR3'])

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __build_chunk_spi_macro(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # Get the device.
        strDeviceName = tChunkNode.getAttribute('device')
        if len(strDeviceName) == 0:
            raise Exception('The SPI macro node has no device attribute!')

        # Parse the data.
        ulDevice = self.__parse_numeric_expression(strDeviceName)

        tOptionCompiler = option_compiler.OptionCompiler(
            self.__cPatchDefinitions
        )
        strMacroData = tOptionCompiler.get_spi_macro_data(tChunkNode)

        # Prepend the device and the size.
        sizMacro = len(strMacroData)
        if sizMacro > 255:
            raise Exception('The SPI macro is too long. The header can only '
                            'indicate up to 255 bytes.')
        strData = chr(ulDevice) + chr(sizMacro) + strMacroData

        # Pad the macro to a multiple of dwords.
        strPadding = chr(0x00) * ((4 - (len(strData) % 4)) & 3)
        strChunk = strData + strPadding

        # Convert the padded data to an array.
        aulData = array.array('I')
        aulData.frombytes(strChunk)

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('S', 'P', 'I', 'M'))
        aulChunk.append(len(aulData) + self.__sizHashDw)
        aulChunk.extend(aulData)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __build_chunk_skip_header(self, tChunkAttributes, atParserState):
        tChunkNode = tChunkAttributes['tNode']

        # Get the device.
        strAbsolute = tChunkNode.getAttribute('absolute')
        sizAbsolute = len(strAbsolute)
        strRelative = tChunkNode.getAttribute('relative')
        sizRelative = len(strRelative)
        strFill = tChunkNode.getAttribute('fill')
        sizFill = len(strFill)
        tNodeFile = None

        strAbsFilePath = None
        # Loop over all children.
        for tChildNode in tChunkNode.childNodes:
            # Is this a node element?
            if tChildNode.nodeType == tChildNode.ELEMENT_NODE:
                # Is this a 'File' node?
                if tChildNode.localName == 'File':
                    tNodeFile = tChildNode
                    # Get the file name.
                    strFileName = tNodeFile.getAttribute('name')
                    if len(strFileName) == 0:
                        raise Exception('The file node has no '
                                        'name attribute!')

                    # Search the file in the current working folder and all
                    # include paths.
                    strAbsFilePath = self.__find_file(strFileName)
                    if strAbsFilePath is None:
                        raise Exception('File %s not found!' % strFileName)

        sizSkip = 0
        sizSkipParameter = 0

        ucFill = 0xff
        if sizFill != 0:
            ucFill = self.__parse_numeric_expression(strFill)
            if ucFill < 0:
                raise Exception('Skip does not accept a negative fill '
                                'value:' % ucFill)
            if ucFill > 0xff:
                raise Exception('Skip does not accept a fill value larger '
                                'than 8 bit:' % ucFill)

        # Get the current offset in bytes.
        sizOffsetCurrent = atParserState['ulCurrentOffset']
        # Add the size of the SKIP chunk itself to the current position.
        if(
            (self.__strNetxType == 'NETX4000_RELAXED') or
            (self.__strNetxType == 'NETX4000') or
            (self.__strNetxType == 'NETX4100')
        ):
            sizOffsetCurrent += (1 + 1 + self.__sizHashDw) * 4
        elif(
            (self.__strNetxType == 'NETX90_MPW') or
            (self.__strNetxType == 'NETX90') or
            (self.__strNetxType == 'NETX90B')
        ):
            sizOffsetCurrent += (1 + 1 + self.__sizHashDw) * 4
        else:
            raise Exception('Continue here!')
        sizOffsetNew = sizOffsetCurrent

        if(
            (sizAbsolute == 0) and
            (sizRelative == 0) and
            (strAbsFilePath is None)
        ):
            raise Exception('The skip node has no "absolute", "relative" '
                            'or "file" attribute!')
        elif (sizAbsolute != 0) and (sizRelative != 0):
            raise Exception('The skip node has an "absolute" and a '
                            '"relative" attribute!')
        elif sizAbsolute != 0:
            # Get the new absolute offset in bytes.
            sizOffsetNew = self.__parse_numeric_expression(strAbsolute)

        elif sizRelative != 0:
            # Parse the data.
            sizSkip = self.__parse_numeric_expression(strRelative)
            if sizSkip < 0:
                raise Exception('Skip does not accept a negative value for '
                                'the relative attribute:' % sizSkip)
            sizOffsetNew = sizOffsetCurrent + sizSkip

        elif strAbsFilePath is not None:
            # No "absolute" or "relative" attribute provided. Use the length
            # of the file as a relative skip.
            sizSkip = os.path.getsize(strAbsFilePath)
            sizOffsetNew = sizOffsetCurrent + sizSkip

        else:
            raise Exception('Internal error!')

        if sizOffsetNew < sizOffsetCurrent:
            raise Exception('Skip tries to set the offset back from %d '
                            'to %d.' % (sizOffsetCurrent, sizOffsetNew))

        if self.__strNetxType == 'NETX90_MPW':
            # The netX90 MPW ROM has a bug in the ROM code.
            # The SKIP chunk for SQI flash forwards the offset by the
            # argument - 1.
            if self.__strDevice == 'SQIROM':
                sizSkip = (sizOffsetNew - sizOffsetCurrent) // 4
                sizSkipParameter = (
                    sizOffsetNew - sizOffsetCurrent + 1 - self.__sizHashDw
                )
            else:
                sizSkip = (sizOffsetNew - sizOffsetCurrent) // 4
                sizSkipParameter = sizSkip

        elif self.__strNetxType == 'NETX4000_RELAXED':
            # The netX4000 relaxed ROM has a bug in the ROM code.
            # The SKIP chunk forwards the offset by the argument - 1.

            # The netX4000 has a lot of XIP areas including SQIROM, SRAM
            # and NAND. Fortunately booting from parallel NOR flash and
            # NAND is unusual. The NAND booter has no ECC support and the
            # parallel NOR flashes are quite unusual in the netX4000 area.
            # That's why we can safely default to SQIROM here and ignore
            # the rest.
            sizSkip = (sizOffsetNew - sizOffsetCurrent) // 4
            sizSkipParameter = (
                sizOffsetNew - sizOffsetCurrent + 1 - self.__sizHashDw
            )

        else:
            sizSkip = (sizOffsetNew - sizOffsetCurrent) // 4
            sizSkipParameter = sizSkip

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('S', 'K', 'I', 'P'))
        aulChunk.append(sizSkipParameter + self.__sizHashDw)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['aulHash'] = array.array('I', strHash)

        return aulChunk, ucFill, sizSkip, strAbsFilePath, tNodeFile

    def __build_chunk_skip(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        aulChunk, ucFill, sizSkip, strAbsFilePath, tNodeFile =\
            self.__build_chunk_skip_header(tChunkAttributes, atParserState)

        # Append the placeholder for the skip area.
        if strAbsFilePath is not None:
            # sizSkip is the numbers of DWORDS to skip. Convert it to bytes.
            sizSkipBytes = sizSkip * 4

            # Is this an ELF file?
            _, strExtension = os.path.splitext(strAbsFilePath)
            if strExtension == '.elf':
                # Get all data from the ELF file.
                strFillData, _ = self.__get_data_contents_elf(
                    tNodeFile,
                    strAbsFilePath,
                    False
                )
                # Cut down the data to the requested size.
                if len(strFillData) > sizSkipBytes:
                    strFillData = strFillData[:sizSkipBytes]

            else:
                # Read at most sizSkipBytes from the file.
                tFile = open(strAbsFilePath, 'rb')
                strFillData = tFile.read(sizSkipBytes)
                tFile.close()

            # Fill up to the requested size.
            sizFillData = len(strFillData)
            if sizFillData < sizSkipBytes:
                strFillData += chr(ucFill) * (sizSkipBytes - sizFillData)

            # Append the contents to the chunk.
            aulChunk.frombytes(strFillData)

        else:
            # Repeat the fill byte in all 4 bytes of a 32 bit value.
            ulFill = ucFill + 256 * ucFill + 65536 * ucFill + 16777216 * ucFill
            aulChunk.extend([ulFill] * sizSkip)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk

    def __build_chunk_skip_incomplete(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        # This chunk is not allowed for images with an end marker.
        if self.__fHasEndMarker is not False:
            raise Exception(
                'A "SkipIncomplete" chunk can not be combined with an end '
                'marker. Set "has_end" to "False".'
            )
        aulChunk, ucFill, sizSkip, strAbsFilePath, tNodeFile =\
            self.__build_chunk_skip_header(tChunkAttributes, atParserState)

        # Do not add any data here. The image has to end after this chunk.
        self.__fMoreChunksAllowed = False

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk

    def __remove_all_whitespace(self, strData):
        astrWhitespace = [' ', '\t', '\n', '\r']
        for strWhitespace in astrWhitespace:
            strData = strData.replace(strWhitespace, '')
        return strData

    # This function gets a data block from the OpenSSL output.
    def __openssl_get_data_block(self, strStdout, strID):
        aucData = array.array('B')
        tReData = re.compile(r'^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2})*:?$')
        iState = 0
        for strLine in iter(strStdout.splitlines()):
            strLine = strLine.strip()
            if iState == 0:
                if strLine == strID:
                    iState = 1
            elif iState == 1:
                tMatch = tReData.search(strLine)
                if tMatch is None:
                    break
                else:
                    for strDataHex in strLine.split(':'):
                        strDataHexStrip = strDataHex.strip()
                        if len(strDataHexStrip) != 0:
                            strDataBin = binascii.unhexlify(strDataHexStrip)
                            aucData.append(ord(strDataBin))

        return aucData

    def __openssl_cut_leading_zero(self, aucData):
        # Does the number start with "00" and is the third digit >= 8?
        if aucData[0] == 0x00 and aucData[1] >= 0x80:
            # Remove the leading "00".
            aucData.pop(0)

    def __openssl_convert_to_little_endian(self, aucData):
        aucData.reverse()

    def __openssl_uncompress_field(self, aucData):
        # The data must not be compressed.
        if aucData[0] != 0x04:
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
        (strStdout, _) = tProcess.communicate(strKeyDER)
        if tProcess.returncode != 0:
            raise Exception('OpenSSL failed with return code %d.' %
                            tProcess.returncode)

        # Try to guess if this is an RSA or ECC key.
        # The text dump of an RSA key has " modulus:", while an ECC key has
        # "priv:".
        iKeyTyp_1ECC_2RSA = None
        atAttr = None
        if strStdout.find('modulus:') != -1:
            # Looks like this is an RSA key.
            iKeyTyp_1ECC_2RSA = 2

            strMatchExponent = 'publicExponent:'
            strMatchModulus = 'modulus:'
            if fIsPublicKey is True:
                strMatchExponent = 'Exponent:'
                strMatchModulus = 'Modulus:'

            # Extract the public exponent.
            tReExp = re.compile(
                r'^{}\s+(\d+)\s+\(0x([0-9a-fA-F]+)\)$'.format(strMatchExponent),
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
            for uiElementId, atAttr in __atKnownRsaSizes.items():
                if (sizMod == atAttr['mod']) and (sizExp == atAttr['exp']):
                    # Found the RSA type.
                    if(
                        (self.__strNetxType == 'NETX90_MPW') or
                        (self.__strNetxType == 'NETX90') or
                        (self.__strNetxType == 'NETX90B')
                    ):
                        uiId = uiElementId + 1
                    else:
                        uiId = uiElementId
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
                for uiElementId, atAttr in __atKnownRsaSizes.items():
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

        elif strStdout.find('priv:') != -1:
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
            tReExp = re.compile(r'^Cofactor:\s+(\d+)\s+\(0x([0-9a-fA-F]+)\)$', re.MULTILINE)
            tMatch = tReExp.search(strStdout)
            if tMatch is None:
                raise Exception('Can not find cofactor!')
            ulCofactor = int(tMatch.group(1))
            ulCofactorHex = int(tMatch.group(2), 16)
            if ulCofactor != ulCofactorHex:
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
            for uiElementId, sizNumbers in __atKnownEccSizes.items():
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
                    if(
                        (self.__strNetxType == 'NETX90_MPW') or
                        (self.__strNetxType == 'NETX90') or
                        (self.__strNetxType == 'NETX90B')
                    ):
                        uiId = uiElementId + 1
                    else:
                        uiId = uiElementId
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

        # A binding block has a size of...
        #   64 bytes on the netX4000
        #   28 bytes on the netX90
        sizBindingExpected = 28
        if(
            (self.__strNetxType == 'NETX4000_RELAXED') or
            (self.__strNetxType == 'NETX4000') or
            (self.__strNetxType == 'NETX4100')
        ):
            sizBindingExpected = 64
        elif(
            (self.__strNetxType == 'NETX90_MPW') or
            (self.__strNetxType == 'NETX90') or
            (self.__strNetxType == 'NETX90B')
        ):
            sizBindingExpected = 28

        if sizBinding != sizBindingExpected:
            raise Exception('The binding in node "%s" has an invalid size '
                            'of %d bytes.' % (strName, sizBinding))

        return aucBinding

    def __root_cert_parse_root_key(self, tNodeParent, atData):
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
                    raise Exception('Failed to read file "%s": '
                                    'file not found.' % strFileName)

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

        # A root cert is for the netX4000, which only knows RSA.
        if iKeyTyp_1ECC_2RSA != 2:
            raise Exception(
                'Trying to use a non-RSA certificate for a root cert.'
            )

        atData['id'] = atAttr['id']
        atData['mod'] = atAttr['mod']
        atData['exp'] = atAttr['exp']
        atData['idx'] = ulIdx

    def __cert_get_key_der(self, tNodeParent, atData):
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
                    raise Exception('Failed to read file "%s": '
                                    'file not found.' % strFileName)

                # Read the complete key.
                tFile = open(strAbsName, 'rb')
                strKeyDER = tFile.read()
                tFile.close()

        if strKeyDER is None:
            raise Exception('No "idx" attribute and no child "File" found!')

        atData['der'] = strKeyDER

    def __root_cert_parse_binding(self, tNodeParent, atData):
        atData['mask'] = self.__cert_parse_binding(tNodeParent, 'Mask')
        atData['ref'] = self.__cert_parse_binding(tNodeParent, 'Ref')

    def __root_cert_parse_new_register_values(self, tNodeParent, atData):
        atValues = array.array('B')

        # Loop over all child nodes.
        for tNode in tNodeParent.childNodes:
            if tNode.nodeType == tNode.ELEMENT_NODE:
                if tNode.localName == 'Value':
                    # Get the bit offset and bit size.
                    strBitOffset = tNode.getAttribute('offset')
                    if len(strBitOffset) == 0:
                        raise Exception('No "offset" attribute found!')
                    ulBitOffset = self.__parse_numeric_expression(
                        strBitOffset
                    )
                    if (ulBitOffset < 0) or (ulBitOffset > 511):
                        raise Exception('The offset is out of range: %d' %
                                        ulBitOffset)

                    strBitSize = tNode.getAttribute('size')
                    if len(strBitSize) == 0:
                        raise Exception('No "size" attribute found!')
                    ulBitSize = self.__parse_numeric_expression(strBitSize)
                    if (ulBitSize < 1) or (ulBitSize > 128):
                        raise Exception('The size is out of range: %d' %
                                        ulBitSize)
                    if (ulBitOffset + ulBitSize) > 512:
                        raise Exception(
                            'The area specified by offset %d and size %d '
                            'exceeds the array.' % (ulBitOffset. ulBitSize)
                        )

                    # Get the text in this node and parse it as hex data.
                    strData = self.__xml_get_all_text(tNode)
                    if strData is None:
                        raise Exception('No text in node "Value" found!')

                    strData = self.__remove_all_whitespace(strData)
                    aucData = binascii.unhexlify(strData)
                    sizData = len(aucData)

                    # The bit size must fit into the data.
                    sizReqBytes = int(math.ceil(ulBitSize / 8.0))
                    if sizReqBytes != sizData:
                        raise Exception(
                            'The size of the data does not match the '
                            'requested size in bits.\n'
                            'Data size: %d bytes\n'
                            'Requested size: %d bits' % (
                                sizData,
                                sizReqBytes
                            )
                        )

                    # Combine the offset and size.
                    ulBnv = ulBitOffset | ((ulBitSize - 1) * 512)

                    # Append all data to the array.
                    atValues.append(ulBnv & 0xff)
                    atValues.append((ulBnv >> 8) & 0xff)
                    atValues.extend(array.array('B', aucData))

                else:
                    raise Exception('Unexpected node: %s' % tNode.localName)

        if len(atValues) > 255:
            raise Exception('The new register values are too long!')

        atData['data'] = atValues

    def __root_cert_parse_trusted_path(self, tNodeParent, atData):
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
            True
        )

        # A root cert is for the netX4000, which only knows RSA.
        if iKeyTyp_1ECC_2RSA != 2:
            raise Exception(
                'Trying to use a non-RSA certificate for a root cert.'
            )

        aucMask = self.__cert_parse_binding(tNodeParent, 'Mask')

        atData['mask'] = aucMask
        atData['id'] = atAttr['id']
        atData['mod'] = atAttr['mod']
        atData['exp'] = atAttr['exp']

    def __root_cert_parse_user_content(self, tNodeParent, atData):
        atValues = array.array('B')

        # Loop over all child nodes.
        for tNode in tNodeParent.childNodes:
            if tNode.nodeType == tNode.ELEMENT_NODE:
                if tNode.localName == 'Text':
                    strData = self.__xml_get_all_text(tNode)
                    atValues.extend(array.array('B', strData))
                elif tNode.localName == 'Hex':
                    strData = self.__xml_get_all_text(tNode)
                    strData = binascii.unhexlify(
                        self.__remove_all_whitespace(strData)
                    )
                    atValues.extend(array.array('B', strData))
                else:
                    raise Exception('Unexpected node: %s' % tNode.localName)

        atData['data'] = atValues

    def __get_chunk_from_file(self, strFile):
        # Read the file.
        tFile = open(strFile, 'rb')
        strData = tFile.read()
        tFile.close()

        # The file size must be a multiple of 32 bit.
        sizData = len(strData)
        if (sizData % 4) != 0:
            raise Exception(
                'The file "%s" has a size which is no multiple of '
                '4 bytes (32 bit).' % strFile
            )

        # Convert the data to an array of 32bit values.
        aulChunk = array.array('I')
        aulChunk.frombytes(strData)

        return aulChunk

    def __build_chunk_root_cert(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        aulChunk = None
        tFileNode = None
        for tNode in tChunkNode.childNodes:
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
                raise Exception('Failed to read file "%s": file not found.' %
                                strFileName)

            aulChunk = self.__get_chunk_from_file(strAbsName)

        else:
            # Generate an array with default values where possible.
            __atRootCert = {
                # The RootPublicKey must be set by the user.
                'RootPublicKey': {
                    'id': None,
                    'mod': None,
                    'exp': None,
                    'idx': None
                },

                # The Binding must be set by the user.
                'Binding': {
                    'mask': None,
                    'ref': None
                },

                # The new register values are empty by default.
                'NewRegisterValues': {
                    'data': ''
                },

                # The TrustedPathLicense must be set by the user.
                'TrustedPathLicense': {
                    'mask': None,
                    'id': None,
                    'mod': None,
                    'exp': None,
                },

                # The TrustedPathCr7Sw must be set by the user.
                'TrustedPathCr7Sw': {
                    'mask': None,
                    'id': None,
                    'mod': None,
                    'exp': None,
                },

                # The TrustedPathCa9Sw must be set by the user.
                'TrustedPathCa9Sw': {
                    'mask': None,
                    'id': None,
                    'mod': None,
                    'exp': None,
                },

                # The user content is empty by default.
                'UserContent': {
                    'data': ''
                }
            }

            # Loop over all children.
            for tNode in tChunkNode.childNodes:
                if tNode.nodeType == tNode.ELEMENT_NODE:
                    if tNode.localName == 'RootPublicKey':
                        self.__root_cert_parse_root_key(
                            tNode,
                            __atRootCert['RootPublicKey'])
                    elif tNode.localName == 'Binding':
                        self.__root_cert_parse_binding(
                            tNode,
                            __atRootCert['Binding']
                        )
                    elif tNode.localName == 'NewRegisterValues':
                        self.__root_cert_parse_new_register_values(
                            tNode,
                            __atRootCert['NewRegisterValues']
                        )
                    elif tNode.localName == 'TrustedPathLicense':
                        self.__root_cert_parse_trusted_path(
                            tNode,
                            __atRootCert['TrustedPathLicense']
                        )
                    elif tNode.localName == 'TrustedPathCr7Sw':
                        self.__root_cert_parse_trusted_path(
                            tNode,
                            __atRootCert['TrustedPathCr7Sw']
                        )
                    elif tNode.localName == 'TrustedPathCa9Sw':
                        self.__root_cert_parse_trusted_path(
                            tNode,
                            __atRootCert['TrustedPathCa9Sw']
                        )
                    elif tNode.localName == 'UserContent':
                        self.__root_cert_parse_user_content(
                            tNode,
                            __atRootCert['UserContent']
                        )
                    else:
                        raise Exception('Unexpected node: %s' %
                                        tNode.localName)

            # Check if all required data was set.
            astrErr = []
            if __atRootCert['RootPublicKey']['id'] is None:
                astrErr.append('No "id" set in the RootPublicKey.')
            if __atRootCert['RootPublicKey']['mod'] is None:
                astrErr.append('No "mod" set in the RootPublicKey.')
            if __atRootCert['RootPublicKey']['exp'] is None:
                astrErr.append('No "exp" set in the RootPublicKey.')
            if __atRootCert['RootPublicKey']['idx'] is None:
                astrErr.append('No "idx" set in the RootPublicKey.')
            if __atRootCert['Binding']['mask'] is None:
                astrErr.append('No "mask" set in the Binding.')
            if __atRootCert['Binding']['ref'] is None:
                astrErr.append('No "ref" set in the Binding.')
            if __atRootCert['TrustedPathLicense']['mask'] is None:
                astrErr.append('No "mask" set in the TrustedPathLicense.')
            if __atRootCert['TrustedPathLicense']['id'] is None:
                astrErr.append('No "id" set in the TrustedPathLicense.')
            if __atRootCert['TrustedPathLicense']['mod'] is None:
                astrErr.append('No "mod" set in the TrustedPathLicense.')
            if __atRootCert['TrustedPathLicense']['exp'] is None:
                astrErr.append('No "exp" set in the TrustedPathLicense.')
            if __atRootCert['TrustedPathCr7Sw']['mask'] is None:
                astrErr.append('No "mask" set in the TrustedPathCr7Sw.')
            if __atRootCert['TrustedPathCr7Sw']['id'] is None:
                astrErr.append('No "id" set in the TrustedPathCr7Sw.')
            if __atRootCert['TrustedPathCr7Sw']['mod'] is None:
                astrErr.append('No "mod" set in the TrustedPathCr7Sw.')
            if __atRootCert['TrustedPathCr7Sw']['exp'] is None:
                astrErr.append('No "exp" set in the TrustedPathCr7Sw.')
            if __atRootCert['TrustedPathCa9Sw']['mask'] is None:
                astrErr.append('No "mask" set in the TrustedPathCa9Sw.')
            if __atRootCert['TrustedPathCa9Sw']['id'] is None:
                astrErr.append('No "id" set in the TrustedPathCa9Sw.')
            if __atRootCert['TrustedPathCa9Sw']['mod'] is None:
                astrErr.append('No "mod" set in the TrustedPathCa9Sw.')
            if __atRootCert['TrustedPathCa9Sw']['exp'] is None:
                astrErr.append('No "exp" set in the TrustedPathCa9Sw.')
            if len(astrErr) != 0:
                raise Exception('\n'.join(astrErr))

            # Combine all data to the chunk.
            atData = array.array('B')

            atData.append(__atRootCert['RootPublicKey']['id'])
            atData.extend(__atRootCert['RootPublicKey']['mod'])
            atData.extend(__atRootCert['RootPublicKey']['exp'])
            atData.append((__atRootCert['RootPublicKey']['idx']) & 0xff)
            atData.append(
                ((__atRootCert['RootPublicKey']['idx']) >> 8) & 0xff
            )

            atData.extend(__atRootCert['Binding']['mask'])
            atData.extend(__atRootCert['Binding']['ref'])

            sizData = len(__atRootCert['NewRegisterValues']['data'])
            atData.append(sizData)
            atData.extend(__atRootCert['NewRegisterValues']['data'])

            atData.extend(__atRootCert['TrustedPathLicense']['mask'])
            atData.append(__atRootCert['TrustedPathLicense']['id'])
            atData.extend(__atRootCert['TrustedPathLicense']['mod'])
            atData.extend(__atRootCert['TrustedPathLicense']['exp'])

            atData.extend(__atRootCert['TrustedPathCr7Sw']['mask'])
            atData.append(__atRootCert['TrustedPathCr7Sw']['id'])
            atData.extend(__atRootCert['TrustedPathCr7Sw']['mod'])
            atData.extend(__atRootCert['TrustedPathCr7Sw']['exp'])

            atData.extend(__atRootCert['TrustedPathCa9Sw']['mask'])
            atData.append(__atRootCert['TrustedPathCa9Sw']['id'])
            atData.extend(__atRootCert['TrustedPathCa9Sw']['mod'])
            atData.extend(__atRootCert['TrustedPathCa9Sw']['exp'])

            sizData = len(__atRootCert['UserContent']['data'])
            atData.append(sizData & 0xff)
            atData.append((sizData >> 8) & 0xff)
            atData.append((sizData >> 16) & 0xff)
            atData.append((sizData >> 32) & 0xff)
            atData.extend(__atRootCert['UserContent']['data'])

            # Get the key in DER encoded format.
            strKeyDER = self.__keyrom_get_key(
                __atRootCert['RootPublicKey']['idx']
            )

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
            tFile.write(atData.tobytes())
            tFile.close()

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
            strSignature = subprocess.check_output(astrCmd)

            # Remove the temp files.
            os.remove(strPathKeypair)
            os.remove(strPathSignatureInputData)

            # Append the signature to the chunk.
            aulSignature = array.array('B', strSignature)
            atData.extend(aulSignature)

            # Pad the data to a multiple of dwords.
            strData = atData.tobytes()
            strPadding = chr(0x00) * ((4 - (len(strData) % 4)) & 3)
            strChunk = strData + strPadding

            # Convert the padded data to an array.
            aulData = array.array('I')
            aulData.frombytes(strChunk)

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('R', 'C', 'R', 'T'))
            aulChunk.append(len(aulData))
            aulChunk.extend(aulData)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = None

    def __build_chunk_license_cert(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        aulChunk = None
        tFileNode = None
        for tNode in tChunkNode.childNodes:
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
                raise Exception('Failed to read file "%s": file not found.' %
                                strFileName)

            aulChunk = self.__get_chunk_from_file(strAbsName)

        else:
            # Generate an array with default values where possible.
            __atCert = {
                # The key index must be set by the user.
                'Key': {
                    'der': None
                },

                # The Binding must be set by the user.
                'Binding': {
                    'mask': None,
                    'ref': None
                },

                # The new register values are empty by default.
                'NewRegisterValues': {
                    'data': ''
                },

                # The user content is empty by default.
                'UserContent': {
                    'data': ''
                }
            }

            # Loop over all children.
            for tNode in tChunkNode.childNodes:
                if tNode.nodeType == tNode.ELEMENT_NODE:
                    if tNode.localName == 'Key':
                        self.__cert_get_key_der(tNode, __atCert['Key'])
                    elif tNode.localName == 'Binding':
                        self.__root_cert_parse_binding(tNode,
                                                       __atCert['Binding'])
                    elif tNode.localName == 'NewRegisterValues':
                        self.__root_cert_parse_new_register_values(
                            tNode,
                            __atCert['NewRegisterValues']
                        )
                    elif tNode.localName == 'UserContent':
                        self.__root_cert_parse_user_content(
                            tNode,
                            __atCert['UserContent']
                        )
                    else:
                        raise Exception(
                            'Unexpected node: %s' % tNode.localName
                        )

            # Check if all required data was set.
            astrErr = []
            if __atCert['Key']['der'] is None:
                astrErr.append('No key set in the LicenseCert.')
            if __atCert['Binding']['mask'] is None:
                astrErr.append('No "mask" set in the Binding.')
            if __atCert['Binding']['ref'] is None:
                astrErr.append('No "ref" set in the Binding.')
            if len(astrErr) != 0:
                raise Exception('\n'.join(astrErr))

            # Combine all data to the chunk.
            atData = array.array('B')

            atData.extend(__atCert['Binding']['mask'])
            atData.extend(__atCert['Binding']['ref'])

            sizData = len(__atCert['NewRegisterValues']['data'])
            atData.append(sizData)
            atData.extend(__atCert['NewRegisterValues']['data'])

            sizData = len(__atCert['UserContent']['data'])
            atData.append(sizData & 0xff)
            atData.append((sizData >> 8) & 0xff)
            atData.append((sizData >> 16) & 0xff)
            atData.append((sizData >> 32) & 0xff)
            atData.extend(__atCert['UserContent']['data'])

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
            tFile.write(atData.tobytes())
            tFile.close()

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
            strSignature = subprocess.check_output(astrCmd)

            # Remove the temp files.
            os.remove(strPathKeypair)
            os.remove(strPathSignatureInputData)

            # Append the signature to the chunk.
            aulSignature = array.array('B', strSignature)
            atData.extend(aulSignature)

            # Pad the data to a multiple of dwords.
            strData = atData.tobytes()
            strPadding = chr(0x00) * ((4 - (len(strData) % 4)) & 3)
            strChunk = strData + strPadding

            # Convert the padded data to an array.
            aulData = array.array('I')
            aulData.frombytes(strChunk)

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('L', 'C', 'R', 'T'))
            aulChunk.append(len(aulData))
            aulChunk.extend(aulData)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = None

    def __build_chunk_cr7sw(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        aulChunk = None
        tFileNode = None
        for tNode in tChunkNode.childNodes:
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
                    'Failed to read file "%s": file not found.' % strFileName
                )

            aulChunk = self.__get_chunk_from_file(strAbsName)

        else:
            # Generate an array with default values where possible.
            __atCert = {
                # The key index must be set by the user.
                'Key': {
                    'der': None
                },

                # The Binding must be set by the user.
                'Binding': {
                    'mask': None,
                    'ref': None
                },

                # The data must be set by the user.
                'Data': {
                    'data': None,
                    'load_address': None
                },

                # The registers.
                'Execute': {
                    'pfnExecFunction': None,
                    'ulR0': None,
                    'ulR1': None,
                    'ulR2': None,
                    'ulR3': None
                },

                # The user content is empty by default.
                'UserContent': {
                    'data': ''
                }
            }

            # Loop over all children.
            for tNode in tChunkNode.childNodes:
                if tNode.nodeType == tNode.ELEMENT_NODE:
                    if tNode.localName == 'Key':
                        self.__cert_get_key_der(tNode, __atCert['Key'])
                    elif tNode.localName == 'Binding':
                        self.__root_cert_parse_binding(tNode,
                                                       __atCert['Binding'])
                    elif tNode.localName == 'Data':
                        self.__get_data_contents(tNode, __atCert['Data'], True)
                    elif tNode.localName == 'Execute':
                        self.__get_execute_data(tNode, __atCert['Execute'])
                    elif tNode.localName == 'UserContent':
                        self.__root_cert_parse_user_content(
                            tNode,
                            __atCert['UserContent']
                        )
                    else:
                        raise Exception('Unexpected node: %s' %
                                        tNode.localName)

            # Check if all required data was set.
            astrErr = []
            if __atCert['Key']['der'] is None:
                astrErr.append('No key set in the CR7Software.')
            if __atCert['Binding']['mask'] is None:
                astrErr.append('No "mask" set in the Binding.')
            if __atCert['Binding']['ref'] is None:
                astrErr.append('No "ref" set in the Binding.')
            if __atCert['Data']['data'] is None:
                astrErr.append('No "data" set in the Data.')
            if __atCert['Data']['load_address'] is None:
                astrErr.append('No "load_address" set in the Data.')
            if __atCert['Execute']['pfnExecFunction'] is None:
                astrErr.append('No "pfnExecFunction" set in the Execute.')
            if __atCert['Execute']['ulR0'] is None:
                astrErr.append('No "ulR0" set in the Execute.')
            if __atCert['Execute']['ulR1'] is None:
                astrErr.append('No "ulR1" set in the Execute.')
            if __atCert['Execute']['ulR2'] is None:
                astrErr.append('No "ulR2" set in the Execute.')
            if __atCert['Execute']['ulR3'] is None:
                astrErr.append('No "ulR3" set in the Execute.')
            if len(astrErr) != 0:
                raise Exception('\n'.join(astrErr))

            # Combine all data to the chunk.
            atData = array.array('B')

            atData.extend(__atCert['Binding']['mask'])
            atData.extend(__atCert['Binding']['ref'])

            self.__append_32bit(atData, len(__atCert['Data']['data']))
            self.__append_32bit(atData, __atCert['Data']['load_address'])
            atData.extend(array.array('B', __atCert['Data']['data']))

            self.__append_32bit(atData,
                                __atCert['Execute']['pfnExecFunction'])
            self.__append_32bit(atData, __atCert['Execute']['ulR0'])
            self.__append_32bit(atData, __atCert['Execute']['ulR1'])
            self.__append_32bit(atData, __atCert['Execute']['ulR2'])
            self.__append_32bit(atData, __atCert['Execute']['ulR3'])

            self.__append_32bit(atData, len(__atCert['UserContent']['data']))
            atData.extend(__atCert['UserContent']['data'])

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
            tFile.write(atData.tobytes())
            tFile.close()

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
            strSignature = subprocess.check_output(astrCmd)

            # Remove the temp files.
            os.remove(strPathKeypair)
            os.remove(strPathSignatureInputData)

            # Append the signature to the chunk.
            aulSignature = array.array('B', strSignature)
            atData.extend(aulSignature)

            # Pad the data to a multiple of dwords.
            strData = atData.tobytes()
            strPadding = chr(0x00) * ((4 - (len(strData) % 4)) & 3)
            strChunk = strData + strPadding

            # Convert the padded data to an array.
            aulData = array.array('I')
            aulData.frombytes(strChunk)

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('R', '7', 'S', 'W'))
            aulChunk.append(len(aulData))
            aulChunk.extend(aulData)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = None

    def __build_chunk_ca9sw(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        aulChunk = None
        tFileNode = None
        for tNode in tChunkNode.childNodes:
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
                raise Exception('Failed to read file "%s": file not found.' %
                                strFileName)

            aulChunk = self.__get_chunk_from_file(strAbsName)

        else:
            # Generate an array with default values where possible.
            __atCert = {
                # The key index must be set by the user.
                'Key': {
                    'der': None
                },

                # The Binding must be set by the user.
                'Binding': {
                    'mask': None,
                    'ref': None
                },

                # The data must be set by the user.
                'Data': {
                    'data': None,
                    'load_address': None
                },

                # The registers.
                'Execute_Core0': {
                    'pfnExecFunction': None,
                    'ulR0': None,
                    'ulR1': None,
                    'ulR2': None,
                    'ulR3': None
                },
                'Execute_Core1': {
                    'pfnExecFunction': None,
                    'ulR0': None,
                    'ulR1': None,
                    'ulR2': None,
                    'ulR3': None
                },

                # The user content is empty by default.
                'UserContent': {
                    'data': ''
                }
            }

            # Loop over all children.
            for tNode in tChunkNode.childNodes:
                if tNode.nodeType == tNode.ELEMENT_NODE:
                    if tNode.localName == 'Key':
                        self.__cert_get_key_der(tNode, __atCert['Key'])
                    elif tNode.localName == 'Binding':
                        self.__root_cert_parse_binding(
                            tNode,
                            __atCert['Binding']
                        )
                    elif tNode.localName == 'Data':
                        self.__get_data_contents(tNode, __atCert['Data'], True)
                    elif tNode.localName == 'Execute':
                        for tRegistersNode in tNode.childNodes:
                            if tRegistersNode.nodeType == tNode.ELEMENT_NODE:
                                if tRegistersNode.localName == 'Core0':
                                    self.__get_execute_data(
                                        tRegistersNode,
                                        __atCert['Execute_Core0']
                                    )
                                elif tRegistersNode.localName == 'Core1':
                                    self.__get_execute_data(
                                        tRegistersNode,
                                        __atCert['Execute_Core1']
                                    )
                    elif tNode.localName == 'UserContent':
                        self.__root_cert_parse_user_content(
                            tNode,
                            __atCert['UserContent']
                        )
                    else:
                        raise Exception('Unexpected node: %s' %
                                        tNode.localName)

            # Check if all required data was set.
            astrErr = []
            if __atCert['Key']['der'] is None:
                astrErr.append('No key set in the CA9Software.')
            if __atCert['Binding']['mask'] is None:
                astrErr.append('No "mask" set in the Binding.')
            if __atCert['Binding']['ref'] is None:
                astrErr.append('No "ref" set in the Binding.')
            if __atCert['Data']['data'] is None:
                astrErr.append('No "data" set in the Data.')
            if __atCert['Data']['load_address'] is None:
                astrErr.append('No "load_address" set in the Data.')
            if __atCert['Execute_Core0']['pfnExecFunction'] is None:
                astrErr.append('No "pfnExecFunction" set in the Execute.')
            if __atCert['Execute_Core0']['ulR0'] is None:
                astrErr.append('No "ulR0" set in the Execute.')
            if __atCert['Execute_Core0']['ulR1'] is None:
                astrErr.append('No "ulR1" set in the Execute.')
            if __atCert['Execute_Core0']['ulR2'] is None:
                astrErr.append('No "ulR2" set in the Execute.')
            if __atCert['Execute_Core0']['ulR3'] is None:
                astrErr.append('No "ulR3" set in the Execute.')
            if __atCert['Execute_Core1']['pfnExecFunction'] is None:
                astrErr.append('No "pfnExecFunction" set in the Execute.')
            if __atCert['Execute_Core1']['ulR0'] is None:
                astrErr.append('No "ulR0" set in the Execute.')
            if __atCert['Execute_Core1']['ulR1'] is None:
                astrErr.append('No "ulR1" set in the Execute.')
            if __atCert['Execute_Core1']['ulR2'] is None:
                astrErr.append('No "ulR2" set in the Execute.')
            if __atCert['Execute_Core1']['ulR3'] is None:
                astrErr.append('No "ulR3" set in the Execute.')
            if len(astrErr) != 0:
                raise Exception('\n'.join(astrErr))

            # Combine all data to the chunk.
            atData = array.array('B')

            atData.extend(__atCert['Binding']['mask'])
            atData.extend(__atCert['Binding']['ref'])

            self.__append_32bit(atData, len(__atCert['Data']['data']))
            self.__append_32bit(atData, __atCert['Data']['load_address'])
            atData.extend(array.array('B', __atCert['Data']['data']))

            self.__append_32bit(atData,
                                __atCert['Execute_Core0']['pfnExecFunction'])
            self.__append_32bit(atData, __atCert['Execute_Core0']['ulR0'])
            self.__append_32bit(atData, __atCert['Execute_Core0']['ulR1'])
            self.__append_32bit(atData, __atCert['Execute_Core0']['ulR2'])
            self.__append_32bit(atData, __atCert['Execute_Core0']['ulR3'])
            self.__append_32bit(atData,
                                __atCert['Execute_Core1']['pfnExecFunction'])
            self.__append_32bit(atData, __atCert['Execute_Core1']['ulR0'])
            self.__append_32bit(atData, __atCert['Execute_Core1']['ulR1'])
            self.__append_32bit(atData, __atCert['Execute_Core1']['ulR2'])
            self.__append_32bit(atData, __atCert['Execute_Core1']['ulR3'])

            self.__append_32bit(atData, len(__atCert['UserContent']['data']))
            atData.extend(__atCert['UserContent']['data'])

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
            tFile.write(atData.tobytes())
            tFile.close()

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
            strSignature = subprocess.check_output(astrCmd)

            # Remove the temp files.
            os.remove(strPathKeypair)
            os.remove(strPathSignatureInputData)

            # Append the signature to the chunk.
            aulSignature = array.array('B', strSignature)
            atData.extend(aulSignature)

            # Pad the data to a multiple of dwords.
            strData = atData.tobytes()
            strPadding = chr(0x00) * ((4 - (len(strData) % 4)) & 3)
            strChunk = strData + strPadding

            # Convert the padded data to an array.
            aulData = array.array('I')
            aulData.frombytes(strChunk)

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('A', '9', 'S', 'W'))
            aulChunk.append(len(aulData))
            aulChunk.extend(aulData)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = None

    def __build_chunk_memory_device_up(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # The netX90B is the first chip which allows more than one device in
        # an MDUP chunk. All other chips allow only one device.
        if self.__strNetxType == 'NETX90B':
            # Get the comma separated list of devices.
            strDeviceList = tChunkNode.getAttribute('device')
            # Split the list by comma.
            astrDeviceList = strDeviceList.split(',')
            aucDevices = array.array('B')
            for strDevice in astrDeviceList:
                # Parse the data.
                ulDevice = self.__parse_numeric_expression(strDevice.strip())
                if ulDevice < 0:
                    raise Exception('The device attribute does not accept a '
                                    'negative value:' % ulDevice)
                if ulDevice > 0xff:
                    raise Exception('The device attribute must not be larger '
                                    'than 0xff:' % ulDevice)

                aucDevices.append(ulDevice)

            if len(aucDevices) == 0:
                raise Exception('The device attribute must not be empty.')
            if len(aucDevices) > 12:
                raise Exception('The device attribute must not have more '
                                'than 12 entries on the netX90B.')

            # Pad the data with 0x00 (NOP) to a multiple of 4.
            sizPadding = (4 - (len(aucDevices) & 3) & 3)
            aucDevices.extend([0] * sizPadding)

            # Get the size of the data in DWORDs.
            sizDataDW = len(aucDevices) // 4

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('M', 'D', 'U', 'P'))
            aulChunk.append(sizDataDW + self.__sizHashDw)
            aulChunk.frombytes(aucDevices.tobytes())

        else:
            # Get the device.
            strDevice = tChunkNode.getAttribute('device')

            # Parse the data.
            ulDevice = self.__parse_numeric_expression(strDevice)
            if ulDevice < 0:
                raise Exception('The device attribute does not accept a '
                                'negative value:' % ulDevice)
            if ulDevice > 0xff:
                raise Exception('The device attribute must not be larger '
                                'than 0xff:' % ulDevice)

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('M', 'D', 'U', 'P'))
            aulChunk.append(1 + self.__sizHashDw)
            aulChunk.append(ulDevice)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

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

    def __openssl_ecc_get_signature(self, aucSignature, sizKeyInBytes):
        # Get the start of the firt element, which is "r".
        uiLen = aucSignature[1]
        if uiLen >= 128:
            uiLen -= 128
        else:
            uiLen = 0
        uiElementStart = 2 + uiLen

        sizR = aucSignature[uiElementStart + 1]
        aucR = aucSignature[uiElementStart + 2:uiElementStart + 2 + sizR]

        if sizR > sizKeyInBytes + 1:
            raise Exception('The R field is too big. Expected %d bytes, '
                            'but got %d.' % (sizKeyInBytes, sizR))
        elif sizR == sizKeyInBytes + 1:
            self.__openssl_cut_leading_zero(aucR)
        elif sizR < sizKeyInBytes:
            # The signature data is smaller than expected. Pad it with 0x00.
            aucR.extend([0] * (sizKeyInBytes - sizR))
        self.__openssl_convert_to_little_endian(aucR)

        # Get the start of the second element, which is "s".
        uiElementStart = 2 + uiLen + 2 + sizR

        sizS = aucSignature[uiElementStart + 1]
        aucS = aucSignature[uiElementStart + 2:uiElementStart + 2 + sizS]

        if sizS > sizKeyInBytes + 1:
            raise Exception('The S field is too big. Expected %d bytes, '
                            'but got %d.' % (sizKeyInBytes, sizS))
        elif sizS == sizKeyInBytes + 1:
            self.__openssl_cut_leading_zero(aucS)
        elif sizS < sizKeyInBytes:
            # The signature data is smaller than expected. Pad it with 0x00.
            aucS.extend([0] * (sizKeyInBytes - sizS))
        self.__openssl_convert_to_little_endian(aucS)

        # Combine R and S.
        aucSignature = array.array('B')
        aucSignature.extend(aucR)
        aucSignature.extend(aucS)

        return aucSignature

    def __build_chunk_update_secure_info_page(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        aulChunk = None

        # Generate an array with default values where possible.
        __atCert = {
            # The target info page defines which page to modify.
            'TargetInfoPage': None,

            # The RootPublicKey must be set by the user.
            'Key': {
                'type': None,
                'id': None,
                'mod': None,
                'exp': None,
                'der': None
            },
            'KeyIndex': 0xff,

            # The Binding must be set by the user.
            'Binding': {
                'mask': None,
                'value': None
            },

            # The data must be set by the user.
            'Data': {
                'data': None
            }
        }

        # Loop over all children.
        for tNode in tChunkNode.childNodes:
            if tNode.nodeType == tNode.ELEMENT_NODE:
                if tNode.localName == 'TargetInfoPage':
                    atVal = {'CAL': 0, 'COM': 1, 'APP': 2}
                    strTarget = self.__xml_get_all_text(tNode)
                    if strTarget in atVal:
                        uiTarget = atVal[strTarget]
                    else:
                        raise Exception(
                            'Invalid target: "%s". Valid targets: %s' % (
                                strTarget,
                                ', '.join(list(atVal.keys()))
                            )
                        )
                    __atCert['TargetInfoPage'] = uiTarget

                elif tNode.localName == 'Key':
                    self.__usip_parse_trusted_path(tNode, __atCert['Key'])

                elif tNode.localName == 'KeyIndex':
                    # Get the key index
                    strIndex = self.__xml_get_all_text(tNode)
                    if len(strIndex) == 0:
                        raise Exception('"KeyIndex" has no data!')
                    ulKeyIndex = self.__parse_numeric_expression(
                        strIndex
                    )
                    if (ulKeyIndex < 0) or (ulKeyIndex > 255):
                        raise Exception(
                            'The key index is out of range: %d' %
                            ulKeyIndex
                        )
                    __atCert['KeyIndex'] = ulKeyIndex

                elif tNode.localName == 'Binding':
                    __atCert['Binding']['value'] = self.__cert_parse_binding(
                        tNode,
                        'Value'
                    )
                    __atCert['Binding']['mask'] = self.__cert_parse_binding(
                        tNode,
                        'Mask'
                    )

                elif tNode.localName == 'Data':
                    self.__get_data_contents(tNode, __atCert['Data'], False)

                else:
                    raise Exception('Unexpected node: %s' %
                                    tNode.localName)

        # Check if all required data was set.
        astrErr = []
        if __atCert['TargetInfoPage'] is None:
            astrErr.append('No target set in USIP.')
        if __atCert['Data']['data'] is None:
            astrErr.append('No "data" set in USIP.')
        if __atCert['KeyIndex'] == 0xff:
            if __atCert['Key']['der'] is not None:
                astrErr.append('The key index is 0xff, '
                               'but a key set in USIP.')
            if __atCert['Binding']['mask'] is not None:
                astrErr.append('The key index is 0xff, '
                               'but a "mask" set in the Binding.')
            if __atCert['Binding']['value'] is not None:
                astrErr.append('The key index is 0xff, '
                               'but a "value" set in the Binding.')
        else:
            if __atCert['Key']['der'] is None:
                astrErr.append('The key index is not 0xff, '
                               'but no key set in USIP.')
            if __atCert['Binding']['mask'] is None:
                astrErr.append('The key index is not 0xff, '
                               'but no "mask" set in the Binding.')
            if __atCert['Binding']['value'] is None:
                astrErr.append('The key index is not 0xff, '
                               'but no "value" set in the Binding.')
        if len(astrErr) != 0:
            raise Exception('\n'.join(astrErr))

        aucPatchData = array.array('B', __atCert['Data']['data'])
        sizPatchData = len(aucPatchData)

        # Combine all data to the chunk.
        atData = array.array('B')

        # Info page select
        atData.append(__atCert['TargetInfoPage'])
        # key index
        atData.append(__atCert['KeyIndex'])
        # Add the size of the patch data in bytes.
        atData.extend([sizPatchData & 0xff, (sizPatchData >> 8) & 0xff])

        # Is this a secure chunk.
        if __atCert['KeyIndex'] == 0xff:
            # Non-secure.

            # Add the patch data.
            atData.extend(aucPatchData)
            # Pad the patch data with 0x00.
            sizPadding = (4 - (sizPatchData % 4)) & 3
            atData.extend([0] * sizPadding)

            # Convert the padded data to an array.
            aulData = array.array('I')
            aulData.frombytes(atData.tobytes())

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('U', 'S', 'I', 'P'))
            aulChunk.append(len(aulData) + self.__sizHashDw)
            aulChunk.extend(aulData)

            # Get the hash for the chunk.
            tHash = hashlib.sha384()
            tHash.update(aulChunk.tobytes())
            strHash = tHash.digest()
            aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
            aulChunk.extend(aulHash)

            tChunkAttributes['fIsFinished'] = True
            tChunkAttributes['atData'] = aulChunk
            tChunkAttributes['aulHash'] = array.array('I', strHash)

        else:
            # Secure.

            # Add the binding.
            atData.extend(__atCert['Binding']['value'])
            atData.extend(__atCert['Binding']['mask'])

            # Add the padded key.
            iKeyTyp_1ECC_2RSA = __atCert['Key']['iKeyTyp_1ECC_2RSA']
            atAttr = __atCert['Key']['atAttr']
            if iKeyTyp_1ECC_2RSA == 2:
                # Add the algorithm.
                atData.append(iKeyTyp_1ECC_2RSA)
                # Add the strength.
                atData.append(atAttr['id'])
                # Add the public modulus N and fill up to 64 bytes.
                self.__add_array_with_fillup(atData, atAttr['mod'], 512)
                # Add the exponent E.
                atData.extend(atAttr['exp'])
                # Pad the key with 3 bytes.
                atData.extend([0, 0, 0])

            elif iKeyTyp_1ECC_2RSA == 1:
                # Add the algorithm.
                atData.append(iKeyTyp_1ECC_2RSA)
                # Add the strength.
                atData.append(atAttr['id'])
                # Write all fields and fill up to 64 bytes.
                self.__add_array_with_fillup(atData, atAttr['Qx'], 64)
                self.__add_array_with_fillup(atData, atAttr['Qy'], 64)
                self.__add_array_with_fillup(atData, atAttr['a'], 64)
                self.__add_array_with_fillup(atData, atAttr['b'], 64)
                self.__add_array_with_fillup(atData, atAttr['p'], 64)
                self.__add_array_with_fillup(atData, atAttr['Gx'], 64)
                self.__add_array_with_fillup(atData, atAttr['Gy'], 64)
                self.__add_array_with_fillup(atData, atAttr['n'], 64)
                atData.extend([0, 0, 0])
                # Pad the key with 3 bytes.
                atData.extend([0, 0, 0])

            # Add the patch data.
            atData.extend(aucPatchData)
            # Pad the patch data with 0x00.
            sizPadding = (4 - (sizPatchData % 4)) & 3
            atData.extend([0] * sizPadding)

            if iKeyTyp_1ECC_2RSA == 1:
                sizKeyInDwords = len(atAttr['Qx']) / 4
                sizSignatureInDwords = 2 * sizKeyInDwords
            elif iKeyTyp_1ECC_2RSA == 2:
                sizKeyInDwords = len(atAttr['mod']) / 4
                sizSignatureInDwords = sizKeyInDwords

            # Convert the padded data to an array.
            aulData = array.array('I')
            aulData.frombytes(atData.tobytes)

            aulChunk = array.array('I')
            aulChunk.append(self.__get_tag_id('U', 'S', 'I', 'P'))
            aulChunk.append(len(aulData) + sizSignatureInDwords)
            aulChunk.extend(aulData)

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
            tFile.write(aulChunk.tobytes())
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
            aulChunk.frombytes(aucSignature.tobytes())

            tChunkAttributes['fIsFinished'] = True
            tChunkAttributes['atData'] = aulChunk
            tChunkAttributes['aulHash'] = None

    def __build_chunk_hash_table(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        # This chunk must be build in multiple passes as it includes the hash
        # sums of the following chunks.
        #
        # In the first pass, a dummy data block is created as a placeholder.
        # This sets the address to the correct position for the following
        # chunks.
        #
        # In the next passes the hash sum can be collected if the chunks are
        # finished.

        tChunkNode = tChunkAttributes['tNode']

        # Get the number of chunks to include in the hash table.
        ulNumberOfHashes = None
        strNumberOfHashes = tChunkNode.getAttribute('entries')
        if len(strNumberOfHashes) != 0:
            ulNumberOfHashes = int(strNumberOfHashes, 0)
            if (ulNumberOfHashes < 1) or (ulNumberOfHashes > 8):
                raise Exception(
                    'The number of hashes is invalid: %d' % ulNumberOfHashes
                )

        # Get the required size of the chunk. Default to "None" which means
        # no required size.
        ulRequiredSizeInBytes = None
        strRequiredSizeInBytes = tChunkNode.getAttribute('size')
        if len(strRequiredSizeInBytes) != 0:
            ulRequiredSizeInBytes = int(strRequiredSizeInBytes, 0)
            if ulRequiredSizeInBytes < 1:
                raise Exception(
                    'The required size must be positive: %d' %
                    ulRequiredSizeInBytes
                )
            if (ulRequiredSizeInBytes & 3) != 0:
                raise Exception(
                    'The required size must be a multiple of 4: %d' %
                    ulRequiredSizeInBytes
                )
            # There should be an upper limit or some idiots will generate
            # 16MB chunks.
            if ulRequiredSizeInBytes > 65536:
                raise Exception(
                    'The required size must be smaller than 65536: %d' %
                    ulRequiredSizeInBytes
                )

        __atData = {
            'TargetInfoPage': None,

            # The RootPublicKey must be set by the user.
            'Key': {
                'type': None,
                'id': None,
                'mod': None,
                'exp': None,
                'der': None
            },

            'RootKeyIndex': None,

            # The Binding must be set by the user.
            'Binding': {
                'mask': None,
                'ref': None
            }
        }

        # Loop over all children.
        for tNode in tChunkNode.childNodes:
            if tNode.nodeType == tNode.ELEMENT_NODE:
                if tNode.localName == 'TargetInfoPage':
                    atVal = {'CAL': 0, 'COM': 1, 'APP': 2}
                    strTarget = self.__xml_get_all_text(tNode)
                    if strTarget in atVal:
                        uiTarget = atVal[strTarget]
                    else:
                        raise Exception(
                            'Invalid target: "%s". Valid targets: %s' % (
                                strTarget,
                                ', '.join(list(atVal.keys()))
                            )
                        )
                    __atData['TargetInfoPage'] = uiTarget

                elif tNode.localName == 'Key':
                    self.__usip_parse_trusted_path(tNode, __atData['Key'])

                elif tNode.localName == 'RootKeyIndex':
                    # Get the root key index
                    strIndex = self.__xml_get_all_text(tNode)
                    if len(strIndex) == 0:
                        raise Exception('"RootKeyIndex" has no data!')
                    ulRootKeyIndex = self.__parse_numeric_expression(
                        strIndex
                    )
                    if (ulRootKeyIndex < 0) or (ulRootKeyIndex > 31):
                        raise Exception(
                            'The root key index is out of range: %d' %
                            ulRootKeyIndex
                        )
                    __atData['RootKeyIndex'] = ulRootKeyIndex

                elif tNode.localName == 'Binding':
                    __atData['Binding']['value'] = self.__cert_parse_binding(
                        tNode,
                        'Value'
                    )
                    __atData['Binding']['mask'] = self.__cert_parse_binding(
                        tNode,
                        'Mask'
                    )

                else:
                    raise Exception('Unexpected node: %s' %
                                    tNode.localName)

        # Check if all required data was set.
        astrErr = []
        if __atData['TargetInfoPage'] is None:
            astrErr.append('No target info page set in HTBL.')
        if __atData['Key']['der'] is None:
            astrErr.append('No key set in HTBL.')
        if __atData['RootKeyIndex'] is None:
            astrErr.append('No root key index set in HTBL.')
        if __atData['Binding']['mask'] is None:
            astrErr.append('No "mask" set in the Binding.')
        if __atData['Binding']['value'] is None:
            astrErr.append('No "value" set in the Binding.')
        if len(astrErr) != 0:
            raise Exception('\n'.join(astrErr))

        # Get the size of the signature.
        iKeyTyp_1ECC_2RSA = __atData['Key']['iKeyTyp_1ECC_2RSA']
        atAttr = __atData['Key']['atAttr']
        if iKeyTyp_1ECC_2RSA == 1:
            sizKeyInDwords = len(atAttr['Qx']) / 4
            sizSignatureInDwords = 2 * sizKeyInDwords
        elif iKeyTyp_1ECC_2RSA == 2:
            sizKeyInDwords = len(atAttr['mod']) / 4
            sizSignatureInDwords = sizKeyInDwords

        # The minimum size of the HTBL chunk is...
        #    4 bytes ID
        sizChunkMinimumInBytes = 4
        #    4 bytes length
        sizChunkMinimumInBytes += 4
        #    1 byte info page select
        sizChunkMinimumInBytes += 1
        #    1 byte root key index
        sizChunkMinimumInBytes += 1
        #    1 byte number of hashes "n"
        sizChunkMinimumInBytes += 1
        #    1 byte fill data
        sizChunkMinimumInBytes += 1
        #   56 bytes binding
        sizChunkMinimumInBytes += 56
        #  0 or 520 bytes embedded key
        if __atData['RootKeyIndex'] < 16:
            sizChunkMinimumInBytes += 520
        #   48 * "n" bytes hash table
        sizChunkMinimumInBytes += ulNumberOfHashes * 48
        #  "s" bytes for the signature
        sizChunkMinimumInBytes += sizSignatureInDwords * 4

        if ulRequiredSizeInBytes is None:
            sizFillUpInDwords = 0
        else:
            if sizChunkMinimumInBytes > ulRequiredSizeInBytes:
                raise Exception('The HashTable size has a minimum size of %d bytes, which exceeds the requested size of %d bytes.' % (sizChunkMinimumInBytes, ulRequiredSizeInBytes))

            sizFillUpInDwords = (ulRequiredSizeInBytes - sizChunkMinimumInBytes) / 4
        sizChunkMinimumSizeInDwords = sizChunkMinimumInBytes / 4

        uiPass = atParserState['uiPass']
        if uiPass == 0:
            # In pass 0 only reserve space.
            aulChunk = array.array(
                'I',
                [0] * (sizChunkMinimumSizeInDwords + sizFillUpInDwords)
            )

            tChunkAttributes['fIsFinished'] = False
            tChunkAttributes['atData'] = aulChunk
            tChunkAttributes['aulHash'] = None

        else:
            sizAllChunks = len(atAllChunks)
            sizHtblFirstChunk = uiChunkIndex + 1
            sizHtblLastChunkPlus1 = sizHtblFirstChunk + ulNumberOfHashes

            # Are enough chunks left?
            if sizHtblLastChunkPlus1 > sizAllChunks:
                raise Exception(
                    'The hash table should include the chunks [%d,%d[ '
                    'but there are only %d chunks.' % (
                        sizHtblFirstChunk,
                        sizHtblLastChunkPlus1,
                        sizAllChunks
                    )
                )

            # This is the list of chunk names which require a hash table
            # entry. Other chunks are not allowed to prevent confusion.
            astrAllowedChunks = [
                'Options',         # OPTS
                'SpiMacro',        # SPIM
                'MemoryDeviceUp',  # MDUP
                'Firewall',        # FRWL
                'Skip',            # SKIP
                'SecureCopy',      # SCPY
                'Text',            # TEXT
                'XIP',             # This is done with a TEXT chunk.
                'Data',            # DATA
                'Register',        # REGI
                'Next',            # NEXT
                'Execute'          # EXEC
            ]

            # Collect hash sums of the next chunks.
            atHashes = []
            for uiChunkIndex in range(sizHtblFirstChunk, sizHtblLastChunkPlus1):
                tAttr = atAllChunks[uiChunkIndex]

                # Is this one of the chunks which needs a hash entry?
                strChunkName = tAttr['strName']
                if strChunkName not in astrAllowedChunks:
                    raise Exception('A "%s" chunk can not be included in a HashTable.' % strChunkName)

                # Is this chunk already finished?
                if tAttr['fIsFinished'] is not True:
                    # The chunk is not finished. Try again in the next pass.
                    break
                else:
                    # Add the hash to the list.
                    atHashes.append(tAttr['aulHash'])

            # Found all hashes?
            if len(atHashes) == ulNumberOfHashes:
                # Yes, all hashes found. Now build the chunk.

                # Combine all data for the chunk.
                aucData = array.array('B')

                # Info page select
                aucData.append(__atData['TargetInfoPage'])
                # root key index
                aucData.append(__atData['RootKeyIndex'])
                # Add the number of hashes.
                aucData.append(ulNumberOfHashes)
                # Add one dummy byte of 0x00.
                aucData.append(0x00)
                # Add the binding.
                aucData.extend(__atData['Binding']['value'])
                aucData.extend(__atData['Binding']['mask'])

                if __atData['RootKeyIndex'] < 16:
                    # Add the padded key.
                    iKeyTyp_1ECC_2RSA = __atData['Key']['iKeyTyp_1ECC_2RSA']
                    atAttr = __atData['Key']['atAttr']
                    if iKeyTyp_1ECC_2RSA == 2:
                        # Add the algorithm.
                        aucData.append(iKeyTyp_1ECC_2RSA)
                        # Add the strength.
                        aucData.append(atAttr['id'])
                        # Add the public modulus N and fill up to 64 bytes.
                        self.__add_array_with_fillup(aucData, atAttr['mod'], 512)
                        # Add the exponent E.
                        aucData.extend(atAttr['exp'])
                        # Pad the key with 3 bytes.
                        aucData.extend([0, 0, 0])

                    elif iKeyTyp_1ECC_2RSA == 1:
                        # Add the algorithm.
                        aucData.append(iKeyTyp_1ECC_2RSA)
                        # Add the strength.
                        aucData.append(atAttr['id'])
                        # Write all fields and fill up to 64 bytes.
                        self.__add_array_with_fillup(aucData, atAttr['Qx'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['Qy'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['a'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['b'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['p'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['Gx'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['Gy'], 64)
                        self.__add_array_with_fillup(aucData, atAttr['n'], 64)
                        aucData.extend([0, 0, 0])
                        # Pad the key with 3 bytes.
                        aucData.extend([0, 0, 0])

                # Append all hashes.
                for atHash in atHashes:
                    aucData.frombytes(atHash.tobytes())

                aulChunk = array.array('I')
                # Add the ID.
                aulChunk.append(self.__get_tag_id('H', 'T', 'B', 'L'))
                # The size field does not include the ID and itself.
                aulChunk.append(sizChunkMinimumSizeInDwords + sizFillUpInDwords - 2)
                # Add the data part.
                aulChunk.frombytes(aucData.tobytes())
                # Append the fill-up.
                aulChunk.extend([0] * sizFillUpInDwords)

                # Get the key in DER encoded format.
                strKeyDER = __atData['Key']['der']

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
                tFile.write(aulChunk.tobytes())
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
                aulChunk.frombytes(aucSignature.tobytes())

                tChunkAttributes['fIsFinished'] = True
                tChunkAttributes['atData'] = aulChunk
                tChunkAttributes['aulHash'] = None

    def __build_chunk_next(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        ulDevice = None
        ulOffsetInBytes = None

        # Loop over all children.
        for tNode in tChunkNode.childNodes:
            if tNode.nodeType == tNode.ELEMENT_NODE:
                if tNode.localName == 'Device':
                    strDevice = self.__xml_get_all_text(tNode)
                    if len(strDevice) == 0:
                        raise Exception(
                            'The Next node has no "Device" child.'
                        )

                    ulDevice = self.__parse_numeric_expression(
                        strDevice
                    )

                elif tNode.localName == 'Offset':
                    strOffset = self.__xml_get_all_text(tNode)
                    if len(strOffset) == 0:
                        raise Exception(
                            'The Next node has no "Offset" child.'
                        )

                    ulOffsetInBytes = self.__parse_numeric_expression(
                        strOffset
                    )

        # Check if all required data was set.
        astrErr = []
        if ulDevice is None:
            astrErr.append('No device set in NEXT.')
        if ulOffsetInBytes is None:
            astrErr.append('No offset set in NEXT.')
        if len(astrErr) != 0:
            raise Exception('\n'.join(astrErr))

        # The offset must be a multiple of DWORDs.
        if (ulOffsetInBytes % 4) != 0:
            raise Exception(
                'The offset %d is no multiple of DWORDS.' % ulOffsetInBytes
            )

        # Convert the offset in bytes to an offset in DWORDs.
        ulOffsetInDwords = ulOffsetInBytes / 4

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('N', 'E', 'X', 'T'))
        aulChunk.append(2 + self.__sizHashDw)
        aulChunk.append(ulDevice)
        aulChunk.append(ulOffsetInDwords)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = None

    def __build_chunk_daxz(self, tChunkAttributes, atParserState, uiChunkIndex, atAllChunks):
        tChunkNode = tChunkAttributes['tNode']

        # Get the working address.
        strWorkingAddress = tChunkNode.getAttribute('working_address')
        if len(strWorkingAddress) == 0:
            raise Exception('The Concat node has no '
                            'address attribute!')

        pulWorkingAddress = self.__parse_numeric_expression(strWorkingAddress)

        # Get the data block.
        atData = {}
        self.__get_data_contents(tChunkNode, atData, True)
        strData = atData['data']
        pulLoadAddress = atData['load_address']

        # Pad the data to a multiple of DWORDs.
        strPadding = chr(0x00) * ((4 - (len(strData) % 4)) & 3)
        strPaddedData = strData + strPadding

        # Convert the padded data to an array.
        aulData = array.array('I')
        aulData.frombytes(strPaddedData)

        aulChunk = array.array('I')
        aulChunk.append(self.__get_tag_id('D', 'A', 'X', 'Z'))
        aulChunk.append(len(aulData) + 2 + self.__sizHashDw)
        aulChunk.append(pulWorkingAddress)
        aulChunk.append(pulLoadAddress)
        aulChunk.extend(aulData)

        # Get the hash for the chunk.
        tHash = hashlib.sha384()
        tHash.update(aulChunk.tobytes())
        strHash = tHash.digest()
        aulHash = array.array('I', strHash[:self.__sizHashDw * 4])
        aulChunk.extend(aulHash)

        tChunkAttributes['fIsFinished'] = True
        tChunkAttributes['atData'] = aulChunk
        tChunkAttributes['aulHash'] = array.array('I', strHash)

    def __string_to_bool(self, strBool):
        strBool = strBool.upper()
        if(
            (strBool == 'TRUE') or
            (strBool == 'T') or
            (strBool == 'YES') or
            (strBool == 'Y') or
            (strBool == '1')
        ):
            fBool = True
        elif(
            (strBool == 'FALSE') or
            (strBool == 'F') or
            (strBool == 'NO') or
            (strBool == 'N') or
            (strBool == '0')
        ):
            fBool = False
        else:
            fBool = None
        return fBool

    def __add_chunk(self, atChunks, strName, tNode, pfnParser):
        tAttr = {
            'strName': strName,
            'pfnParser': pfnParser,
            'fIsFinished': False,
            'tNode': tNode,
            'atData': None,
            'aulHash': None
        }
        atChunks.append(tAttr)

    def __collect_chunks(self, tImageNode):
        atChunks = []

        # Map the chunk name to...
        #  'fn': a handler function
        #  'img': a list of image types where this chunk is valid
        #  'netx': a list of netX types where this chunk is valid
        atKnownChunks = {
            'Options': {
                'fn': self.__build_chunk_options,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90B',
                    'NETX90'
                ]
            },
            'Register': {
                'fn': self.__build_chunk_register,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    # 'NETX4000_RELAXED',
                    # 'NETX4000',
                    # 'NETX4100',
                    # 'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'Firewall': {
                'fn': self.__build_chunk_firewall,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    # 'NETX4000_RELAXED',
                    # 'NETX4000',
                    # 'NETX4100',
                    # 'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'Data': {
                'fn': self.__build_chunk_data,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    self.__IMAGE_TYPE_COM_INFO_PAGE,
                    self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'Text': {
                'fn': self.__build_chunk_text,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'XIP': {
                'fn': self.__build_chunk_xip,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'Execute': {
                'fn': self.__build_chunk_execute,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'ExecuteCA9': {
                'fn': self.__build_chunk_execute_ca9,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    # 'NETX90_MPW',
                    # 'NETX90',
                    # 'NETX90B'
                ]
            },
            'SpiMacro': {
                'fn': self.__build_chunk_spi_macro,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'Skip': {
                'fn': self.__build_chunk_skip,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'SkipIncomplete': {
                'fn': self.__build_chunk_skip_incomplete,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'RootCert': {
                'fn': self.__build_chunk_root_cert,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    # 'NETX90_MPW',
                    # 'NETX90',
                    # 'NETX90B'
                ]
            },
            'LicenseCert': {
                'fn': self.__build_chunk_license_cert,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    # 'NETX90_MPW',
                    # 'NETX90',
                    # 'NETX90B'
                ]
            },
            'CR7Software': {
                'fn': self.__build_chunk_cr7sw,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    # 'NETX90_MPW',
                    # 'NETX90',
                    # 'NETX90B'
                ]
            },
            'CA9Software': {
                'fn': self.__build_chunk_ca9sw,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    # 'NETX90_MPW',
                    # 'NETX90',
                    # 'NETX90B'
                ]
            },
            'MemoryDeviceUp': {
                'fn': self.__build_chunk_memory_device_up,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    'NETX56',
                    'NETX4000_RELAXED',
                    'NETX4000',
                    'NETX4100',
                    'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'UpdateSecureInfoPage': {
                'fn': self.__build_chunk_update_secure_info_page,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    # 'NETX4000_RELAXED',
                    # 'NETX4000',
                    # 'NETX4100',
                    # 'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'HashTable': {
                'fn': self.__build_chunk_hash_table,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    # 'NETX4000_RELAXED',
                    # 'NETX4000',
                    # 'NETX4100',
                    # 'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'Next': {
                'fn': self.__build_chunk_next,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    # 'NETX4000_RELAXED',
                    # 'NETX4000',
                    # 'NETX4100',
                    # 'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
            'DaXZ': {
                'fn': self.__build_chunk_daxz,
                'img': [
                    self.__IMAGE_TYPE_REGULAR,
                    self.__IMAGE_TYPE_ALTERNATIVE,
                    self.__IMAGE_TYPE_INTRAM,
                    # self.__IMAGE_TYPE_SECMEM,
                    # self.__IMAGE_TYPE_COM_INFO_PAGE,
                    # self.__IMAGE_TYPE_APP_INFO_PAGE
                ],
                'netx': [
                    # 'NETX56',
                    # 'NETX4000_RELAXED',
                    # 'NETX4000',
                    # 'NETX4100',
                    # 'NETX90_MPW',
                    'NETX90',
                    'NETX90B'
                ]
            },
        }

        # Loop over all nodes, these are the chunks.
        for tChunkNode in tImageNode.childNodes:
            if tChunkNode.nodeType == tChunkNode.ELEMENT_NODE:
                strChunkName = tChunkNode.localName
                if strChunkName in atKnownChunks:
                    tAttr = atKnownChunks[strChunkName]
                    # Is the chunk available for the image type?
                    if self.__tImageType not in tAttr['img']:
                        raise Exception(
                            '%s chunks are not allowed in the current '
                            'image type.' % strChunkName
                        )
                    if self.__strNetxType not in tAttr['netx']:
                        raise Exception(
                            '%s chunks are not allowed on %s' %
                            (
                                strChunkName,
                                self.__strNetxType
                            )
                        )
                    self.__add_chunk(
                        atChunks,
                        strChunkName,
                        tChunkNode,
                        tAttr['fn']
                    )
                else:
                    raise Exception('Unknown chunk ID: %s' % strChunkName)

        return atChunks

    def __parse_chunks(self, atChunks):
        # Get the initial offset.
        ulOffsetInitial = self.__ulStartOffset
        if self.__fHasHeader is True:
            ulOffsetInitial += 64

        # Create a new state.
        atState = {
            'uiPass': 0,
            'atChunks': [],
            'ulCurrentOffset': ulOffsetInitial,
            'fMoreChunksAllowed': True
        }

        # All operations should be finished in 2 passes.
        fAllChunksAreFinished = None
        for uiPass in range(0, 2):
            # Set the current pass.
            atState['uiPass'] = uiPass

            atState['ulCurrentOffset'] = ulOffsetInitial
            atState['fMoreChunksAllowed'] = True
            fAllChunksAreFinished = True

            # Loop over all chunks.
            sizChunks = len(atChunks)
            for uiChunkIndex in range(0, sizChunks):
                tAttr = atChunks[uiChunkIndex]

                if atState['fMoreChunksAllowed'] is not True:
                    raise Exception('No more chunks allowed.')

                # Call the parser if the chunk is not finished yet.
                if tAttr['fIsFinished'] is not True:
                    # Call the parser.
                    tAttr['pfnParser'](tAttr, atState, uiChunkIndex, atChunks)
                    # Update the global finish state.
                    fAllChunksAreFinished &= tAttr['fIsFinished']
                    # Update the current position.
                    if self.__tImageType == self.__IMAGE_TYPE_SECMEM:
                        sizChunkInBytes = len(tAttr['atData'])
                    else:
                        sizChunkInBytes = len(tAttr['atData']) * 4
                    atState['ulCurrentOffset'] += sizChunkInBytes

            if fAllChunksAreFinished is True:
                break

        if fAllChunksAreFinished is False:
            raise Exception('Some chunks are still not finished.')

        # Collect all data from the chunks.
        for tAttr in atChunks:
            self.__atChunkData.extend(tAttr['atData'])

    def parse_image(self, tInput):
        # Parsing an image requires the patch definition.
        if self.__cPatchDefinitions is None:
            raise Exception(
                'A patch definition is required for the "parse_image" '
                'function, but none was specified!'
            )

        # Initialize the list of dependencies.
        self.__astrDependencies = []

        # Read the complete input file as plain text.
        if os.path.isfile(tInput):
            tFile = open(tInput, 'rt')
        else:
            path = os.path.join(os.path.dirname(os.path.realpath(__file__)), tInput)
            tFile = open(path, 'rt')

        strFileContents = tFile.read()
        tFile.close()

        # Replace and convert to XML.
        tXml = self.__plaintext_to_xml_with_replace(
            strFileContents,
            self.__atGlobalDefines,
            True
        )
        tXmlRootNode = tXml.documentElement

        # Preprocess the image.
        self.__preprocess(tXml)

        # Get the type of the image. Default to "REGULAR".
        strType = tXmlRootNode.getAttribute('type')
        if len(strType) != 0:
            if strType not in self.__astrToImageType:
                raise Exception('Invalid image type: "%s"' % strType)
            self.__tImageType = self.__astrToImageType[strType]
        else:
            # Set the default type.
            self.__tImageType = self.__IMAGE_TYPE_REGULAR

        # Alternative images are allowed on netX4000 and netX90.
        astrNetxWithAlternativeImages = [
            'NETX4000_RELAXED',
            'NETX4000',
            'NETX4100',
            'NETX90',
            'NETX90B'
        ]
        if self.__tImageType == self.__IMAGE_TYPE_ALTERNATIVE:
            if self.__strNetxType not in astrNetxWithAlternativeImages:
                raise Exception(
                    'The image type "ALTERNATIVE" is not allowed for the '
                    'netX "%s".' % self.__strNetxType
                )

        # Check if a header should be written to the output file.
        # SECMEM and info page images never have a header.
        if(
            (self.__tImageType == self.__IMAGE_TYPE_SECMEM) or
            (self.__tImageType == self.__IMAGE_TYPE_COM_INFO_PAGE) or
            (self.__tImageType == self.__IMAGE_TYPE_APP_INFO_PAGE)
        ):
            fHasHeader = False
        else:
            fHasHeader = True
            strBool = tXmlRootNode.getAttribute('has_header')
            if len(strBool) != 0:
                fBool = self.__string_to_bool(strBool)
                if fBool is not None:
                    fHasHeader = fBool
        self.__fHasHeader = fHasHeader

        # Check if an end marker should be written to the output file.
        # SECMEM and info page images never have a header.
        if(
            (self.__tImageType == self.__IMAGE_TYPE_SECMEM) or
            (self.__tImageType == self.__IMAGE_TYPE_COM_INFO_PAGE) or
            (self.__tImageType == self.__IMAGE_TYPE_APP_INFO_PAGE)
        ):
            fHasEndMarker = False
        else:
            fHasEndMarker = True
            strBool = tXmlRootNode.getAttribute('has_end')
            if len(strBool) != 0:
                fBool = self.__string_to_bool(strBool)
                if fBool is not None:
                    fHasEndMarker = fBool
        self.__fHasEndMarker = fHasEndMarker

        # SECMEM images are byte based, all other images are DWORD based.
        if self.__tImageType == self.__IMAGE_TYPE_SECMEM:
            self.__atChunkData = array.array('B')
        else:
            self.__atChunkData = array.array('I')

        # Get the hash size.
        # Default to 12 DWORDS for info page images.
        # Default to 0 DWORDS for SECMEM images.
        # Default to 1 DWORD for all other images.
        if(self.__tImageType == self.__IMAGE_TYPE_SECMEM):
            uiHashSize = 0
        elif(
            (self.__tImageType == self.__IMAGE_TYPE_COM_INFO_PAGE) or
            (self.__tImageType == self.__IMAGE_TYPE_APP_INFO_PAGE)
        ):
            uiHashSize = 12
        else:
            strHashSize = tXmlRootNode.getAttribute('hashsize')
            if len(strHashSize) != 0:
                uiHashSize = int(strHashSize)
                if (uiHashSize < 1) or (uiHashSize > 12):
                    raise Exception('Invalid hash size: %d' % uiHashSize)
            else:
                # Set the default hash size.
                uiHashSize = 1
        self.__sizHashDw = uiHashSize

        # Get the start offset. Default to 0.
        ulStartOffset = 0
        strStartOffset = tXmlRootNode.getAttribute('offset')
        if len(strStartOffset) != 0:
            ulStartOffset = int(strStartOffset, 0)
            if ulStartOffset < 0:
                raise Exception(
                    'The start offset in the <HBootImage> tag is invalid: %d' % ulStartOffset
                )
            elif ulStartOffset % 4 != 0:
                raise Exception(
                    'The start offset in the <HBootImage> tag must be a multiple of 4: %d' % ulStartOffset
                )

        self.__ulStartOffset = ulStartOffset

        # Get the size and value for a padding. Default to 0 bytes of 0xff.
        ulPaddingPreSize = 0
        ucPaddingPreValue = 0xff
        strPaddingPreSize = tXmlRootNode.getAttribute('padding_pre_size')
        if len(strPaddingPreSize) != 0:
            ulPaddingPreSize = int(strPaddingPreSize, 0)
            if ulPaddingPreSize < 0:
                raise Exception(
                    'The padding pre size is invalid: %d' % ulPaddingPreSize
                )
        strPaddingPreValue = tXmlRootNode.getAttribute('padding_pre_value')
        if len(strPaddingPreValue) != 0:
            ucPaddingPreValue = int(strPaddingPreValue, 0)
            if (ucPaddingPreValue < 0) or (ucPaddingPreValue > 0xff):
                raise Exception(
                    'The padding pre value is invalid: %d' % ucPaddingPreValue
                )
        self.__ulPaddingPreSize = ulPaddingPreSize
        self.__ucPaddingPreValue = ucPaddingPreValue

        # Get the device. Default to "UNSPECIFIED".
        astrValidDeviceNames = [
            'UNSPECIFIED',
            'INTFLASH',
            'SQIROM',
            'SQIROM0',
            'SQIROM1'
        ]
        strDevice = tXmlRootNode.getAttribute('device')
        if len(strDevice) == 0:
            strDevice = 'UNSPECIFIED'
        else:
            # Check the device name.
            if strDevice not in astrValidDeviceNames:
                raise Exception(
                    'Invalid device name specified: "%s". '
                    'Valid names are %s.' % (
                        strDevice,
                        ', '.join(astrValidDeviceNames)
                    )
                )
        self.__strDevice = strDevice

        # The image accepts chunks.
        # This can change after special chunks like "SkipIncomplete".
        self.__fMoreChunksAllowed = True

        # Loop over all children.
        atChunks = []
        for tImageNode in tXmlRootNode.childNodes:
            # Is this a node element?
            if tImageNode.nodeType == tImageNode.ELEMENT_NODE:
                # Is this a 'Header' node?
                if tImageNode.localName == 'Header':
                    if(
                        (self.__tImageType == self.__IMAGE_TYPE_SECMEM) or
                        (self.__tImageType == self.__IMAGE_TYPE_COM_INFO_PAGE) or
                        (self.__tImageType == self.__IMAGE_TYPE_APP_INFO_PAGE)
                    ):
                        raise Exception(
                            'Header overrides are not allowed in '
                            'this image type.'
                        )
                    self.__parse_header_options(tImageNode)

                elif tImageNode.localName == 'Chunks':
                    atChunks.extend(self.__collect_chunks(tImageNode))
                else:
                    raise Exception(
                        'Unknown element: %s' % tImageNode.localName
                    )

        self.__parse_chunks(atChunks)

    def __crc7(self, strData):
        ucCrc = 0
        for uiByteCnt in range(0, len(strData)):
            ucByte = ord(strData[uiByteCnt])
            for _ in range(0, 8):
                ucBit = (ucCrc ^ ucByte) & 0x80
                ucCrc <<= 1
                ucByte <<= 1
                if ucBit != 0:
                    ucCrc ^= 0x07
            ucCrc &= 0xff

        return ucCrc

    def write(self, strTargetPath):
        """ Write all compiled chunks to the file strTargetPath . """

        if self.__tImageType == self.__IMAGE_TYPE_SECMEM:
            # Collect data for zone 2 and 3.
            aucZone2 = None
            aucZone3 = None

            # Get the size of the complete image.
            uiImageSize = self.__atChunkData.buffer_info()[1]

            # Up to 29 bytes fit into zone 2.
            if uiImageSize <= 29:
                aucZone2 = array.array('B')
                aucZone3 = array.array('B')

                # Set the length.
                aucZone2.append(uiImageSize)

                # Add the options.
                aucZone2.extend(self.__atChunkData)

                # Fill up zone2 to 29 bytes.
                if uiImageSize < 29:
                    aucZone2.extend([0x00] * (29 - uiImageSize))

                # Set the revision.
                aucZone2.append(self.__SECMEM_ZONE2_REV1_0)

                # Set the checksum.
                ucCrc = self.__crc7(aucZone2.tobytes())
                aucZone2.append(ucCrc)

                # Clear zone 3.
                aucZone3.extend([0] * 32)

            # Zone 2 and 3 together can hold up to 61 bytes.
            elif uiImageSize <= 61:
                aucTmp = array.array('B')

                # Set the length.
                aucTmp.append(uiImageSize)

                # Add the options.
                aucTmp.extend(self.__atChunkData)

                # Fill up the data to 61 bytes.
                if uiImageSize < 61:
                    aucTmp.extend([0x00] * (61 - uiImageSize))

                # Set the revision.
                aucTmp.append(self.__SECMEM_ZONE2_REV1_0)

                # Get the checksum.
                ucCrc = self.__crc7(aucTmp.tobytes())

                # Get the first 30 bytes as zone2.
                aucZone2 = aucTmp[0:30]

                # Add the revision.
                aucZone2.append(self.__SECMEM_ZONE2_REV1_0)

                # Add the checksum.
                aucZone2.append(ucCrc)

                # Place the rest of the data into zone3.
                aucZone3 = aucTmp[30:62]

            else:
                raise Exception(
                    'The image is too big for a SECMEM. It must be 61 bytes '
                    'or less, but it has %d bytes.' % uiImageSize
                )

            # Get a copy of the chunk data.
            atChunks = array.array('B')
            atChunks.extend(aucZone2)
            atChunks.extend(aucZone3)

            # Do not add headers in a SECMEM image.
            atHeader = array.array('B')

            # Do not add end markers in a SECMEM image.
            atEndMarker = array.array('B')

        elif(
            (self.__tImageType == self.__IMAGE_TYPE_COM_INFO_PAGE) or
            (self.__tImageType == self.__IMAGE_TYPE_APP_INFO_PAGE)
        ):
            atChunks = self.__atChunkData

            # The chunk data must have a size of 4048 bytes (1012 DWORDS).
            sizChunksInDWORDs = len(atChunks)
            if sizChunksInDWORDs != 1012:
                raise Exception(
                    'The info page data without the hash must be 1012 '
                    'bytes, but it is %d bytes.' % sizChunksInDWORDs
                )

            # Build the hash for the info page.
            tHash = hashlib.sha384()
            tHash.update(atChunks.tobytes())
            strHash = tHash.digest()
            aulHash = array.array('I', strHash)
            atChunks.extend(aulHash)

        else:
            # Get a copy of the chunk data.
            atChunks = array.array('I', self.__atChunkData)

            # Terminate the chunks with a DWORD of 0.
            atChunks.append(0x00000000)

            # Generate the standard header.
            atHeaderStandard = self.__build_standard_header(atChunks)

            # Insert flasher parameters if selected.
            if self.__fSetFlasherParameters == True:
                self.__set_flasher_parameters(atHeaderStandard)

            # Combine the standard header with the overrides.
            atHeader = self.__combine_headers(atHeaderStandard)

            # Get a fresh copy of the chunk data.
            atChunks = array.array('I', self.__atChunkData)

            # Terminate the chunks with a DWORD of 0.
            atEndMarker = array.array('I', [0x00000000])

        # Write all components to the output file.
        tFile = open(strTargetPath, 'wb')
        if self.__ulPaddingPreSize != 0:
            atPadding = array.array(
                'B',
                [self.__ucPaddingPreValue] * self.__ulPaddingPreSize
            )
            atPadding.tofile(tFile)
        if self.__fHasHeader is True:
            atHeader.tofile(tFile)
        atChunks.tofile(tFile)
        if self.__fHasEndMarker is True:
            atEndMarker.tofile(tFile)
        tFile.close()

    def dependency_scan(self, strInput):
        tXml = xml.dom.minidom.parse(strInput)

        # Initialize the list of dependencies.
        self.__astrDependencies = []

        # Preprocess the image.
        self.__preprocess(tXml)

        # Scan the complete definition for "File" nodes.
        atFileNodes = tXml.getElementsByTagName('File')
        for tNode in atFileNodes:
            strFileName = tNode.getAttribute('name')
            if strFileName is not None:
                if strFileName[0] == '@':
                    strFileId = strFileName[1:]
                    if strFileId not in self.__atKnownFiles:
                        raise Exception(
                            'Unknown reference to file ID "%s".' % strFileName
                        )
                    strFileName = self.__atKnownFiles[strFileId]
                self.__astrDependencies.append(strFileName)

        return self.__astrDependencies
