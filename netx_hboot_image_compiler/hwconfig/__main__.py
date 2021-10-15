from . import hwconfig, atLogLevels

import argparse, logging
            
    
tMainParser = argparse.ArgumentParser(usage='hwconfig [options]')
tMainParser.add_argument('-V', '--version', action='version', version=hwconfig.version_string,
                     help='Print version info and exit.')
tMainParser.add_argument('-v', '--verbose',
                     dest='tVerboseLevel',
                     required=False,
                     default='info',
                     choices=list(atLogLevels.keys()),
                     metavar='LEVEL',
                     help='Set the log level to LEVEL. Possible values for LEVEL are %s' % ', '.join(list(atLogLevels.keys())))
                     
tSubparsers = tMainParser.add_subparsers(help='sub-command -h')

tParserA = tSubparsers.add_parser('make_hboot_xml',   
    description = 'Generate a HBoot XML file from a hardware configuration.', 
    help='make_hboot_xml -h')

tParserB = tSubparsers.add_parser('list_supported_targets', 
    description = 'List the supported chip types, boards and chip/board combinations',
    help='list_supported_targets -h')

tParserC = tSubparsers.add_parser('list_dynamic_cfg', 
    description = 'List the dynamic XML files for the hardware config GUI in netx studio.',
    help='list_dynamic_cfg -h')

tParserD = tSubparsers.add_parser('update_hwconfig', 
    description = 'Update a hardware config from an older version to be compatible  with the current hwconfig GUI.',
    help='update_hwconfig -h')

tParserA.add_argument('-p', '--peripherals',
                     dest='strPeripheralsFile',
                     required=True,
                     metavar='FILE',
                     help='Read the peripheral definition from FILE.')
tParserA.add_argument('-v', '--verbose',
                     dest='tVerboseLevel',
                     required=False,
                     default='info',
                     choices=atLogLevels.keys(),
                     metavar='LEVEL',
                     help='Set the log level to LEVEL. Possible values for LEVEL are %s' % ', '.join(atLogLevels.keys()))
tParserA.add_argument('strHwConfigFile',
                     metavar='FILE',
                     help='Read the hwconfig from FILE.')
tParserA.add_argument('strOutputFile',
                     metavar='FILE',
                     help='Write the HBoot image to FILE.')
tParserA.set_defaults(func=hwconfig.make_hboot_xml)


# Arguments for list_supported_targets
tParserB.add_argument('-o', '--output', 
                     dest='strOutputFile',
                     required=False,
                     metavar='FILE',
                     help='write the supported targets to FILE.')
tParserB.set_defaults(func=hwconfig.list_supported_targets)
 
# Arguments for list_dynamic_cfg
tParserC.add_argument('-c', '--chiptype',
                     dest='strChipType',
                     required=True,
                     metavar='CHIP_TYPE',
                     choices=hwconfig.astrCmdLineChiptypes,
                     help='Set the chip type to CHIP_TYPE. Possible values are %s.' % ', '.join(hwconfig.astrCmdLineChiptypes))
tParserC.add_argument('-b', '--board',
                     dest='strBoard',
                     required=False,
                     metavar='BOARDNAME',
                     help='Get only configuration overlays applicable to BOARDNAME.')
tParserC.add_argument('-s', '--sniplib_path',
                     dest='strLibPath',
                     required=False,
                     metavar='PATH',
                     help='Set the path to the sniplib to PATH.')
tParserC.add_argument('-o', '--output', 
                     dest='strOutputFile',
                     required=False,
                     metavar='FILE',
                     help='write the dynamic cfg to FILE.')
tParserC.set_defaults(func=hwconfig.list_dynamic_cfg)

tParserD.add_argument('strHwConfigFile',
                     metavar='FILE',
                     help='Read the hwconfig from FILE.')
tParserD.add_argument('strOutputFile',
                     nargs='?',
                     metavar='FILE',
                     help='Write the updated hwconfig to FILE.')
tParserD.set_defaults(func=hwconfig.update_hwconfig)


# Parse args
tArgs = tMainParser.parse_args()

# Create the logger object.
tLogLevel = atLogLevels[tArgs.tVerboseLevel]
logging.basicConfig(format='%(asctime)-15s [%(levelname)s]: %(message)s', level=tLogLevel)

if 'strChipType' in tArgs:
    tArgs.strChipType = hwconfig.resolve_chip_type_alias(tArgs.strChipType)

# Call the selected function if successful.
tArgs.func(tArgs)