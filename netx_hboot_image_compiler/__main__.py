# -*- coding: utf-8 -*-

import argparse
import os.path
import re

from . import hboot_image


tParser = argparse.ArgumentParser(usage='usage: hboot_image [options]')
tParser.add_argument('-n', '--netx-type',
                     dest='strNetxType',
                     required=True,
                     choices=[
                         'NETX56',
                         'NETX90',
                         'NETX90B',
                         'NETX90_MPW',
                         'NETX4000_RELAXED',
                         'NETX4000',
                         'NETX4100'
                     ],
                     metavar='NETX',
                     help='Build the image for netx type NETX.')
tParser.add_argument('-c', '--objcopy',
                     dest='strObjCopy',
                     required=False,
                     default='objcopy',
                     metavar='FILE',
                     help='Use FILE as the objcopy tool.')
tParser.add_argument('-d', '--objdump',
                     dest='strObjDump',
                     required=False,
                     default='objdump',
                     metavar='FILE',
                     help='Use FILE as the objdump tool.')
tParser.add_argument('-k', '--keyrom',
                     dest='strKeyRomPath',
                     required=False,
                     default=None,
                     metavar='FILE',
                     help='Read the keyrom data from FILE.')
tParser.add_argument('-p', '--patch-table',
                     dest='strPatchTablePath',
                     required=False,
                     default=None,
                     metavar='FILE',
                     help='Read the patch table from FILE.')
tParser.add_argument('-r', '--readelf',
                     dest='strReadElf',
                     required=False,
                     default='readelf',
                     metavar='FILE',
                     help='Use FILE as the readelf tool.')
tParser.add_argument('-v', '--verbose',
                     dest='fVerbose',
                     required=False,
                     default=False,
                     action='store_const', const=True,
                     help='Be more verbose.')
tParser.add_argument('-A', '--alias',
                     dest='astrAliases',
                     required=False,
                     action='append',
                     metavar='ALIAS=FILE',
                     help='Add an alias in the form ALIAS=FILE.')
tParser.add_argument('-D', '--define',
                     dest='astrDefines',
                     required=False,
                     action='append',
                     metavar='NAME=VALUE',
                     help='Add a define in the form NAME=VALUE.')
tParser.add_argument('-I', '--include',
                     dest='astrIncludePaths',
                     required=False,
                     action='append',
                     metavar='PATH',
                     help='Add PATH to the list of include paths.')
tParser.add_argument('-S', '--sniplib',
                     dest='astrSnipLib',
                     required=False,
                     action='append',
                     metavar='PATH',
                     help='Add PATH to the list of sniplib paths.')
tParser.add_argument('--openssl-options',
                     dest='astrOpensslOptions',
                     required=False,
                     action='append',
                     metavar='SSLOPT',
                     help='Add SSLOPT to the arguments for OpenSSL.')
tParser.add_argument('strInputFile',
                     metavar='FILE',
                     help='Read the HBoot definition from FILE.')
tParser.add_argument('strOutputFile',
                     metavar='FILE',
                     help='Write the HBoot image to FILE.')
tArgs = tParser.parse_args()

# Set the default for the patch table here.
atDefaultPatchTables = {
    'NETX56': 'hboot_netx56_patch_table.xml',
    'NETX90': 'hboot_netx90_patch_table.xml',
    'NETX90B': 'hboot_netx90b_patch_table.xml',
    'NETX90_MPW': 'hboot_netx90_mpw_patch_table.xml',
    'NETX4000_RELAXED': 'hboot_netx4000_relaxed_patch_table.xml',
    'NETX4000': 'hboot_netx4000_patch_table.xml',
    'NETX4100': 'hboot_netx4000_patch_table.xml'
}
if tArgs.strPatchTablePath is None:
    tArgs.strPatchTablePath = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        atDefaultPatchTables[tArgs.strNetxType]
    )

# Parse all alias definitions.
atKnownFiles = {}
if tArgs.astrAliases is not None:
    tPattern = re.compile(r'([a-zA-Z0-9_]+)=(.+)$')
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

# Parse all defines.
atDefinitions = {}
if tArgs.astrDefines is not None:
    tPattern = re.compile(r'([a-zA-Z0-9_]+)=(.+)$')
    for strDefine in tArgs.astrDefines:
        tMatch = re.match(tPattern, strDefine)
        if tMatch is None:
            raise Exception('Invalid define: "%s". '
                            'It must be "NAME=VALUE" instead.' % strDefine)
        strName = tMatch.group(1)
        strValue = tMatch.group(2)
        if strName in atDefinitions:
            raise Exception(
                'Double defined name "%s". '
                'The old value "%s" should be overwritten with "%s".' % (
                    strName,
                    atKnownFiles[strName],
                    strValue
                )
            )
        atDefinitions[strName] = strValue

# Set an empty list of include paths if nothing was specified.
if tArgs.astrIncludePaths is None:
    tArgs.astrIncludePaths = []

# Set an empty list of sniplib paths if nothing was specified.
if tArgs.astrSnipLib is None:
    tArgs.astrSnipLib = []

tEnv = {'OBJCOPY': tArgs.strObjCopy,
        'OBJDUMP': tArgs.strObjDump,
        'READELF': tArgs.strReadElf,
        'HBOOT_INCLUDE': tArgs.astrIncludePaths}

tCompiler = hboot_image.HbootImage(
    tEnv,
    tArgs.strNetxType,
    defines=atDefinitions,
    includes=tArgs.astrIncludePaths,
    known_files=atKnownFiles,
    patch_definition=tArgs.strPatchTablePath,
    verbose=tArgs.fVerbose,
    sniplibs=tArgs.astrSnipLib,
    keyrom=tArgs.strKeyRomPath,
    openssloptions=tArgs.astrOpensslOptions
)
tCompiler.parse_image(tArgs.strInputFile)
tCompiler.write(tArgs.strOutputFile)
