# -*- coding: utf-8 -*-
  
import argparse
import logging
import os.path
import fnmatch
import string
import xml.etree.ElementTree as ElementTree
#import ElementTree_keep_attr_order as ElementTree
import xml.dom.minidom as dom
from . import hwconfig_version

# Import version info.
# This is the version of the HWConfig tool.
# (This information has been previously written to hwconfig_version.py.)
version_major = hwconfig_version.major
version_minor = hwconfig_version.minor
version_micro = hwconfig_version.micro
version_clean = hwconfig_version.clean
version_commit_count = hwconfig_version.commit_count
version_commit_hash = hwconfig_version.commit_hash

# Build the string reported by the --version option.
# The version is based on the last tag.
# If we are not on a tag without further commits, append the hash of the
# current head and the number of commits.
__revision__ = '%d.%d.%d' % (version_major, version_minor, version_micro)
version_string = 'hwconfig v%s by cthelen@hilscher.com' % __revision__
if version_clean!=True:
    version_string = version_string + ', DEVELOPMENT: Git %s, %d commits after tag' % (version_commit_hash, version_commit_count)

if version_clean==True:
    hwconfig_tool_version_short = __revision__
else:
    hwconfig_tool_version_short = __revision__ + '.' + version_commit_hash
        
class HwConfig:
    __strDocVersion = None # tool_version
    __strChipType = None

    __atPadCtrl = None
    __atMMIO = None
    __atSDRAM = None
    __atPeripherals = None

    # The peripherals object.
    __cPeripherals = None

    # Collect the output lines in this array.
    __astrOutput = None

    def __init__(self, cPeripherals):
        logging.debug('Created a new hwconfig instance.')
        self.__cPeripherals = cPeripherals
        
    def __init__(self):
        logging.debug('Created a new hwconfig instance.')
        
    def set_peripherals(self, cPeripherals):
        self.__cPeripherals = cPeripherals

    def get_doc_version(self):
        return self.__strDocVersion
        
    def set_doc_version(self, strVersion):
        self.__strDocVersion = strVersion 
        self.__tXmlRoot.set('tool_version', strVersion)

    def get_chip_type(self):
        return self.__strChipType

    def __parse_pad_config(self, tXmlRoot):
        # Collect all IO config entries.
        #  <pin id="HIF_D8" function="mmio8" peripheral="mmio8" resistor="" drive_strength=""/>
        atPadCtrl = []
        for tNodePin in tXmlRoot.findall('pad_config/pin'):
            fAllOK = True
            tPadCtrl = {}
            # The id attribute is required.
            if 'id' not in tNodePin.attrib:
                logging.error('Missing attribute "id" in pin definition.')
                fAllOK = False
            else:
                tPadCtrl['id'] = tNodePin.attrib['id']
            # The drive_strength attribute is optional.
            if 'drive_strength' in tNodePin.attrib:
                tPadCtrl['drive_strength'] = tNodePin.attrib['drive_strength']
            else:
                tPadCtrl['drive_strength'] = None
            # The pull_enable attribute is optional.
            if 'pull_enable' in tNodePin.attrib:
                tPadCtrl['pull_enable'] = tNodePin.attrib['pull_enable']
            else:
                tPadCtrl['pull_enable'] = None
            # The input_enable attribute is optional.
            if 'input_enable' in tNodePin.attrib:
                tPadCtrl['input_enable'] = tNodePin.attrib['input_enable']
            else:
                tPadCtrl['input_enable'] = None
            if fAllOK is not True:
                raise Exception('Invalid hwconfig file.')

            # Add the new pin dataset.
            atPadCtrl.append(tPadCtrl)

        return atPadCtrl

    def __dump_pad_ctrl(self, atPadCtrl):
        # Show all pins.
        for tPadCtrl in atPadCtrl:
            logging.debug('pin(id="%s", drive_strength="%s", pull_enable="%s, input_enable=%s")' % (tPadCtrl['id'], tPadCtrl['drive_strength'], tPadCtrl['pull_enable'], tPadCtrl['input_enable']))

    def __parse_mmios(self, tXmlRoot):
        # Collect al MMIO pins.
        atMMIO = []
        for tNodeMmio in tXmlRoot.findall('mmio_config/mmio'):
            fAllOK = True
            tMmio = {}
            for strKey in ['id', 'signal']:
                if strKey in tNodeMmio.attrib:
                    tMmio[strKey] = tNodeMmio.attrib[strKey]
                else:
                    logging.error('Missing attribute "s" in MMIO definition.' % strKey)
                    fAllOK = False
            if fAllOK is not True:
                raise Exception('Invalid hwconfig file.')
            # Add the new MMIO dataset.
            atMMIO.append(tMmio)

        return atMMIO

    def __dump_mmios(self, atMMIO):
        # Show all MMIO pins.
        for tMmio in atMMIO:
            logging.debug('mmio(id="%s", signal="%s")' % (tMmio['id'], tMmio['signal']))

    def __parse_sdram(self, tXmlRoot):
        atSDRAM = None

        # Does the definition have an SDRAM?
        tNodeSdram = tXmlRoot.find('sdram_config')
        if tNodeSdram is not None:
            # The SDRAM configuration must either be a type string or the 3 register values.
            if 'type' in tNodeSdram.attrib:
                strSdramType = tNodeSdram.attrib['type']
                logging.debug('Found SDRAM definition with the type "%s".' % strSdramType)

                atSDRAM = {}
                atSDRAM['type'] = strSdramType

            else:
                # Expect the attributes general_ctrl, timing_ctrl and mode_register.
                fAllOK = True
                tNodeSdramGeneralCtrl = tNodeSdram.find('general_ctrl')
                if tNodeSdramGeneralCtrl is None:
                    logging.error('Missing node "general_ctrl" in SDRAM definition.')
                    fAllOK = False
                else:
                    strGeneralCtrl = tNodeSdramGeneralCtrl.text.strip()
                    try:
                        ulSdramGeneralCtrl = int(strGeneralCtrl, 0)
                    except ValueError:
                        logging.error('Failed to convert the SDRAM general_ctrl to a number: "%s"' % strGeneralCtrl)
                        fAllOK = False
                tNodeSdramTimingCtrl = tNodeSdram.find('timing_ctrl')
                if tNodeSdramTimingCtrl is None:
                    logging.error('Missing node "timing_ctrl" in SDRAM definition.')
                    fAllOK = False
                else:
                    strTimingCtrl = tNodeSdramTimingCtrl.text.strip()
                    try:
                        ulSdramTimingCtrl = int(strTimingCtrl, 0)
                    except ValueError:
                        logging.error('Failed to convert the SDRAM timing_ctrl to a number: "%s"' % strTimingCtrl)
                        fAllOK = False
                tNodeSdramModeRegister = tNodeSdram.find('mode_register')
                if tNodeSdramModeRegister is None:
                    logging.error('Missing node "mode_register" in SDRAM definition.')
                    fAllOK = False
                else:
                    strModeRegister = tNodeSdramModeRegister.text.strip()
                    try:
                        ulSdramModeRegister = int(strModeRegister, 0)
                    except ValueError:
                        logging.error('Failed to convert the SDRAM mode_register to a number: "%s"' % strModeRegister)
                        fAllOK = False

                if fAllOK is not True:
                    raise Exception('Invalid hwconfig file.')

                # Mask out bit 23 of the timing_ctrl register. This is set to 1 in earlier releases.
                ulSdramTimingCtrl &= 0xff7fffff

                atSDRAM = {}
                atSDRAM['general_ctrl'] = ulSdramGeneralCtrl
                atSDRAM['timing_ctrl'] = ulSdramTimingCtrl
                atSDRAM['mode_register'] = ulSdramModeRegister

        return atSDRAM

    def __parse_peripherals(self, tXmlRoot):
        atPeripherals = []
        for tNodePeripheral in tXmlRoot.findall('peripherals/peripheral'):
            fAllOK = True
            tPeripheral = {}
            # The id attribute is required.
            if 'id' not in tNodePeripheral.attrib:
                logging.error('Missing attribute "id" in peripheral definition.')
                fAllOK = False
            else:
                tPeripheral['id'] = tNodePeripheral.attrib['id']

            # A peripheral can have 0 or 1 configurations, but not more.
            tConfiguration = {}
            tConfigurationNode = None
            strConfigurationID = None
            atVerbatimNodes = []

            if fAllOK is True:
                # Get the configuration.
                for tNode in tNodePeripheral.findall('config'):
                    if tConfigurationNode is None:
                        tConfigurationNode = tNode
                        # The id attribute is required.
                        if 'id' not in tConfigurationNode.attrib:
                            logging.error('Missing attribute "id" in configuration of peripheral "%s".' % tPeripheral['id'])
                            fAllOK = False
                            break
                        else:
                            strConfigurationID = tConfigurationNode.attrib['id']
                    else:
                        logging.error('More than one configuration definition for peripheral "%s".' % tPeripheral['id'])
                        fAllOK = False
                        break

            if (fAllOK is True) and (tConfigurationNode is not None):
                # Get all parameters.
                for tNodeParameter in tConfigurationNode.findall('parameter'):
                    strKey = None
                    strValue = None
                    # The id attribute is required.
                    if 'id' not in tNodeParameter.attrib:
                        logging.error('Missing attribute "id" in configuration "%s" of peripheral "%s".' % (strConfigurationID, tPeripheral['id']))
                        fAllOK = False
                    else:
                        strKey = tNodeParameter.attrib['id']
                    # The value attribute is required.
                    if 'value' not in tNodeParameter.attrib:
                        logging.error('Missing attribute "value" in configuration "%s" of peripheral "%s".' % (strConfigurationID, tPeripheral['id']))
                        fAllOK = False
                    else:
                        strValue = tNodeParameter.attrib['value']

                    if (strKey is not None) and (strValue is not None):
                        tConfiguration[strKey] = strValue
                for tNodeVerbatim in tConfigurationNode.findall('verbatim'):
                    atVerbatimNodes.append(tNodeVerbatim)

            if fAllOK is True:
                tPeripheral['config_id'] = strConfigurationID
                tPeripheral['config'] = tConfiguration
                tPeripheral['verbatim'] = atVerbatimNodes


            if fAllOK is not True:
                raise Exception('Invalid hwconfig file.')
            # Add the new peripheral dataset.
            atPeripherals.append(tPeripheral)

        return atPeripherals

    def __dump_peripherals(self, atPeripherals):
        for tPeripheral in atPeripherals:
            print('Peripheral "%s":' % tPeripheral['id'])
            for strKey, strValue in tPeripheral['parameter'].items():
                print('    "%s" = "%s"' % (strKey, strValue))

    def read_hwconfig(self, strInputPath):
        logging.debug('Reading hwconfig from "%s".' % strInputPath)

        tFile = open(strInputPath, 'rt')
        strXml = tFile.read()
        tFile.close()
        tXmlRoot = ElementTree.fromstring(strXml)
        self.__tXmlRoot = tXmlRoot

        # Expect the root node to have the name "hwconfig".
        if tXmlRoot.tag != 'hwconfig':
            logging.error('The root node has an unexpected name. Expected "hwconfig", found "%s".' % tXmlRoot.tag)
            raise Exception('Invalid hwconfig file.')

        # Get the version of the file.
        if 'tool_version' not in tXmlRoot.attrib:
            raise Exception('The root node has no attribute "tool_version".')
        strVersion = tXmlRoot.attrib['tool_version']
        aulVersion = [int(strComponent) for strComponent in strVersion.split('.')]
        astrVersion = [strComponent for strComponent in strVersion.split('.')]
        self.__strDocVersion = '.'.join(astrVersion)
        logging.info('Document version of hardware config is %s.' % self.__strDocVersion)

        if 'chip_type' not in tXmlRoot.attrib:
            raise Exception('The root node has no attribute "chip_type".')
        self.__strChipType = tXmlRoot.attrib['chip_type']
        logging.info('Hardware config for chip type %s.' % self.__strChipType)
        
        atPadConfig = self.__parse_pad_config(tXmlRoot)
        atMmioConfig = self.__parse_mmios(tXmlRoot)
        atPeripherals = self.__parse_peripherals(tXmlRoot)
        atSDRAM = self.__parse_sdram(tXmlRoot)

        self.__atPadCtrl = atPadConfig
        self.__atMMIO = atMmioConfig
        self.__atPeripherals = atPeripherals
        self.__atSDRAM = atSDRAM

#        print 'hwconfig pads:'
#        self.__dump_pad_ctrl(atPadConfig)
#        print 'hwconfig mmios:'
#        self.__dump_mmios(atMmioConfig)
#        print 'Peripherals:'
#        self.__dump_peripherals(atPeripherals)

    def write_hwconfig(self, strOutputPath):
        logging.info('Writing hwconfig to "%s".' % strOutputPath)
        tElementTree = ElementTree.ElementTree(self.__tXmlRoot)
        tFile = open(strOutputPath, 'wt')
        tElementTree.write(tFile, encoding="UTF-8", xml_declaration=True, method="xml")
        tFile.close()

    def apply_pads(self):
        # Loop over all pads.
        for tPadCtrl in self.__atPadCtrl:
            # Get the pad name.
            strPadID = tPadCtrl['id']
            # Get the drive strength.
            tDriveStrength = tPadCtrl['drive_strength']
            # Get the pull enable.
            tPullEnable = tPadCtrl['pull_enable']
            # Get the input enable.
            tInputEnable = tPadCtrl['input_enable']
            # Apply the pad control values.
            self.__cPeripherals.set_pad_ctrl(strPadID, tDriveStrength, tPullEnable, tInputEnable)

    def apply_mmio_config(self):
        # Loop over all pads.
        for tMmio in self.__atMMIO:
            # Get the pad name.
            strID = tMmio['id'].upper()

            # The "signal" attribut must be set.
            tSignal = tMmio['signal']
            if tSignal is not None:
                strSignal = tSignal.upper()
                self.__cPeripherals.mmio_set_signal(strID, strSignal)

    def apply_peripherals(self):
        # Loop over all peripherals.
        for tPeripheral in self.__atPeripherals:
            strID = tPeripheral['id']
            strOwner = 'peripheral %s' % strID
            self.__cPeripherals.apply_peripheral(strID, tPeripheral['config_id'], tPeripheral['config'], tPeripheral['verbatim'], strOwner)

    def apply_sdram(self):
        if self.__atSDRAM is not None:
            atSDRAM = self.__atSDRAM
            self.__cPeripherals.apply_sdram_settings(atSDRAM['general_ctrl'], atSDRAM['timing_ctrl'], atSDRAM['mode_register'])


    #
    # Update SQI config
    # 
    
    astrSqiConfigsToUpdate = ['W25Q32BV', 'W25Q32FV', 'SQI_W25Q32JV']

    atSqiFlashParams = [
        {'id':"bWriteEnable"    ,'value':'0x06'       },
        {'id':"bPageProgram"    ,'value':'0x02'       },
        {'id':"bSectorErase"    ,'value':'0x20'       },
        {'id':"bRead"           ,'value':'0x03'       },
        {'id':"bQuadRead"       ,'value':'0xEB'       },
        {'id':"bReadStatus1"    ,'value':'0x05'       },
        {'id':"bWriteStatus1"   ,'value':'0x01'       },
        {'id':"bReadStatus2"    ,'value':'0x35'       },
        {'id':"bWriteStatus2"   ,'value':'0x31'       },
        {'id':"bAddrBytes"      ,'value':'0x03'       },
        {'id':"bQERType"        ,'value':'4'          },
        {'id':"bEntryType"      ,'value':'1'          },
        {'id':"bExitType"       ,'value':'2'          },
        {'id':"bPollingMethod"  ,'value':'2'          },
        {'id':"bSpiFifoMode"    ,'value':'0'          },
        {'id':"ulPageSize"      ,'value':'0x00000100' }, 
        {'id':"ulSectorSize"    ,'value':'0x00001000' }, 
        {'id':"ulSectorCount"   ,'value':'0x00000400' },
    ]

    
    tReg_SqiromCfg = {
        'path':"register/sqi/sqi_sqirom_cfg", 
        'address':"0xff401678",
        'bitfields':[
            {'id':"enable"          , 'start':0,  'width':1, 'default':0, 'value':1 },
            {'id':"addr_before_cmd" , 'start':1,  'width':1, 'default':0, 'value':1 },
            {'id':"addr_nibbles"    , 'start':2,  'width':2, 'default':1, 'value':1 },
            {'id':"addr_bits"       , 'start':4,  'width':3, 'default':0, 'value':0 },
            {'id':"cmd_byte"        , 'start':8,  'width':8, 'default':0, 'value':0xa5 },
            {'id':"dummy_cycles"    , 'start':16, 'width':4, 'default':2, 'value':4 },
            {'id':"t_csh"           , 'start':20, 'width':2, 'default':0, 'value':0 },
            {'id':"clk_div_val"     , 'start':24, 'width':8, 'default':2, 'value':0 },
        ]
    }
    
    # Bitfields in sqirom_cfg to include in SQI config
    astrSqiromParams = [
        "t_csh",
        "cmd_byte",
        "addr_nibbles",
        "addr_before_cmd",
        "dummy_cycles",
    ]
    
    def upd_sqi_register_set_value(self, tReg, ulVal):
        for tBf in tReg['bitfields']:
            ulMask = 2**tBf['width'] - 1 
            ulBf = (ulVal >> tBf['start']) & ulMask 
            tBf['value'] = ulBf
   
    def update_hwconfig_sqi_param_v1(self):
        fUpdated = False
        logging.debug("update_hwconfig_sqi_param_v1")
        tNodeRoot = self.__tXmlRoot
        tNodeConfig = tNodeRoot.find(".//peripherals//peripheral[@id='sqi']//config")
        if tNodeConfig is not None:
            logging.info("Found SQI config node, updating")
            logging.info("Command/speed parameters")
            
            # Check if the configuration is for one of the known flashes.
            strConfigId = tNodeConfig.get('id')
            if strConfigId is None:
                raise Exception('SQI config ID is missing')
            elif strConfigId == "custom":
                logging.info('Cannot update custom SQI configuration')
            elif strConfigId not in self.astrSqiConfigsToUpdate:
                raise Exception('Cannot update unknown SQI configuration %s' % (strConfigId))
            elif len(tNodeConfig)<3:
                raise Exception('SQI flash parameters are missing or incomplete')
            else:
                # Step 1: insert command/size parameters
                # Check if any of the parameters are present.
                # If none of them are present, insert them.
                # If all of them are present, do nothing.
                # Otherwise, raise an error.
                
                # Formatting:
                # The tail of the first child contains the indentation of the children.
                strParamIndent = tNodeConfig[0].tail
                # The tail of the last child is the indentation of the closing tag.
                strConfigCloseIndent = tNodeConfig[-1].tail
                tNodeConfig[-1].tail = strParamIndent
                
                iExistingParamCount = 0
                for tParam in self.atSqiFlashParams:
                    strXPath = ".//parameter[@id='%s']" % tParam['id']
                    tParamNode = tNodeConfig.find(strXPath)
                    if tParamNode is not None:
                        iExistingParamCount += 1
                
                if iExistingParamCount == 0:
                    logging.info("Adding SQI flash parameters.")
                    for tParam in self.atSqiFlashParams:
                        tParamNode = ElementTree.SubElement(tNodeConfig, 'parameter')
                        for k, v in tParam.items():
                            tParamNode.set(k, v)
                        tParamNode.tail=strParamIndent
                        
                elif iExistingParamCount == len(self.atSqiFlashParams):
                    logging.info("SQI Flash parameters are complete, no update necessary.")
                    
                else:
                    raise Exception("Invalid hardware config: partial SQI flash parameters")
                
                # Step 2: convert verbatim nodes with Option sqi_cs0
                #
                # <Option id="sqi_cs0">
                #     <U32>...</U32> - sqirom_cfg value
                #     <U08>...</U08> - activate XIP macro
                #     <U08>...</U08> - deactivate XIP macro
                # </Option>
                # 
                # Extract sqirom_cfg and set parameters accordingly
                # Remove the verbatim node
                
                tNodeVerbatim = tNodeConfig.find(".//verbatim")
                if tNodeVerbatim is not None:
                    logging.info("Found verbatim node")
                    
                    tNodeOpt = tNodeVerbatim.find(".//Option[@id='sqi_cs0']")
                    if tNodeOpt is not None:
                        logging.info("Found Option sqi_cs0")
                        
                        # Check the structure of the option node
                        if len(tNodeOpt) != 3 \
                        or tNodeOpt[0].tag != 'U32' \
                        or tNodeOpt[1].tag != 'U08' \
                        or tNodeOpt[2].tag != 'U08':
                            raise Exception('Option "sqi_cs0" is malformed')
                        
                        # Get the sqirom_cfg value and write it to the register.
                        logging.info("Extracting sqirom_cfg value")
                        tNodeSqiromCfg  = tNodeOpt[0]
                        strSqiromCfg    = tNodeSqiromCfg.text
                        
                        logging.debug("Parsing sqirom_cfg value: %s" % strSqiromCfg)
                        ulSqiromCfg = None
                        try:
                            ulSqiromCfg = int(strSqiromCfg, 0)
                        except:
                            raise Exception('Cannot parse value in option "sqi_cs0": %s' % strSqiromCfg)
                            
                        self.upd_sqi_register_set_value(self.tReg_SqiromCfg, ulSqiromCfg)
    
                    # Remove the node
                    logging.info("Removing verbatim node")
                    tNodeConfig.remove(tNodeVerbatim)
                        
                # Step 3: 
                logging.info("Adding sqirom_cfg parameters.")
                for tBf in self.tReg_SqiromCfg['bitfields']:
                    if tBf['id'] in self.astrSqiromParams:
                        tParamNode = ElementTree.SubElement(tNodeConfig, 'parameter')
                        tParamNode.set('id', tBf['id'])
                        tParamNode.set('value', str(tBf['value']))
                        tParamNode.tail=strParamIndent
                    
                fUpdated = True
            
            
        return fUpdated
    
    
    #
    # Update HWC info
    #
    
    def update_hwconfig_hwcinfo_v1(self):
        fUpdated = False
        logging.debug("update_hwconfig_hwcinfo_v1")
        tNodeRoot = self.__tXmlRoot
        tNodeInfo = tNodeRoot.find(".//peripherals//peripheral[@id='general']//config[@id='default']")
        if tNodeInfo is not None:
            logging.debug("Found HWC info node")
            tNodeStructVersion = tNodeInfo.find("./parameter[@id='struct_version']")
            if tNodeStructVersion is not None:
                strStructVersion = tNodeStructVersion.get('value')
                if strStructVersion is None:
                    raise Exception('Parameter "struct_version" has no value!')
                else:
                    iStructVersion = int(strStructVersion, 0)
                    if iStructVersion == 1:
                    
                        tNodeFileVersion   = tNodeInfo.find("./parameter[@id='file_version']")
                        if tNodeFileVersion is None:
                            raise Exception('Parameter "file_version" is missing from general config.')
                            
                        tNodeFileText      = tNodeInfo.find("./parameter[@id='file_text']")
                        if tNodeFileText is None:
                            raise Exception('Parameter "file_text" is missing from general config.')
                            
                        tNodeFileString    = tNodeInfo.find("./parameter[@id='file_string']")
                        if tNodeFileString is None:
                            raise Exception('Parameter "file_string" is missing from general config.')
                            
                        tNodeManID         = tNodeInfo.find("./parameter[@id='manufacturer_id']")
                        if tNodeManID is None:
                            raise Exception('Parameter "manufacturer_id" is missing from general config.')
                            
                        tNodeDevNum        = tNodeInfo.find("./parameter[@id='device_number']")
                        if tNodeDevNum is None:
                            raise Exception('Parameter "device_number" is missing from general config.')
                            
                        tNodeHWRev         = tNodeInfo.find("./parameter[@id='hardware_revision']")
                        if tNodeHWRev is None:
                            raise Exception('Parameter "hardware_revision" is missing from general config.')
                            
                        strFileText = tNodeFileText.get('value')
                        if strFileText is None:
                            raise Exception('Parameter "file_text" in general config has no value.')
                            
                        strFileString = tNodeFileString.get('value')
                        if strFileString is None:
                            raise Exception('Parameter "file_string" in general config has no value.')

                        logging.info("Found HWC info V1, updating to V2")

                        tNodeStructVersion.set('value', '2')

                        strFileText = strFileText + strFileString
                        iLen = len(strFileText)
                        iMaxLen = 108
                        if iLen>iMaxLen:
                            # This should not happen, as the two partial strings are only 48 chars max.
                            strFileText = strFileText[0:iMaxLen]
                            logging.warning('Truncating file_text in general config')
                        tNodeFileText.set('value', strFileText)
                                                    
                        tNodeInfo.remove(tNodeFileString)
                        tNodeInfo.remove(tNodeManID)
                        tNodeInfo.remove(tNodeDevNum)
                        tNodeInfo.remove(tNodeHWRev)
                        
                        fUpdated = True
        return fUpdated

    #
    # If no board_id attribute is present, set it to "default".
    #
    def update_hwconfig_board_id_default(self):
        fUpdated = False
        logging.debug("update_hwconfig_board_id_default")
        tNodeRoot = self.__tXmlRoot
        if tNodeRoot.tag != "hwconfig":
            raise Exception('root node is not hwconfig!')
        else:
            tNodeHwconfig = tNodeRoot
            if tNodeHwconfig.get('board')is None:
                logging.debug("Setting board ID to 'default'")
                tNodeHwconfig.set('board', 'default')
                fUpdated = True
            
        return fUpdated
        
    #
    # Replace the board ID 'nrp_h90-re' with 'nrp_h90-re_fxdx'  
    #
    def update_hwconfig_board_id_nrp_h90_re(self):
        fUpdated = False
        logging.debug("update_hwconfig_board_id_nrp_h90_re")
        tNodeRoot = self.__tXmlRoot
        if tNodeRoot.tag != "hwconfig":
            raise Exception('root node is not hwconfig!')
        else:
            tNodeHwconfig = tNodeRoot
            strBoardID = tNodeHwconfig.get('board')
            if strBoardID == "nrp_h90-re":
                logging.debug("Found hwconfig node with board ID nrp_h90-re. Updating to nrp_h90-re_fxdx.")
                tNodeHwconfig.set('board', 'nrp_h90-re_fxdx')
                fUpdated = True
        return fUpdated
        
    #
    # Update XM0 peripheral
    # Add the optional xm0_io0 pin 
    # Remove the unused xm0_io1 pin 
    # 
    def update_hwconfig_xm0(self):
        fUpdated = False
        logging.debug("update_hwconfig_xm0")
        tNodeRoot = self.__tXmlRoot

        # Find the XM0 config node. Do nothing if it is not found.
        tNodePeripheralConfig = tNodeRoot.find(".//peripherals//peripheral[@id='xm0']//config[@id='default']")
        if tNodePeripheralConfig is not None:
            logging.debug("Found XM0 config node")

            tNodeIoConfig = tNodeRoot.find(".//io_config")
            if tNodeIoConfig is None:
                raise Exception("Node io_config not found")
                
            tNodePadConfig = tNodeRoot.find(".//pad_config")
            if tNodePadConfig is None:
                raise Exception("Node pad_config not found")
            
            
            # Add parameter node <parameter id="xm0_io0" value="enabled"/>
            logging.debug("Adding parameter to enable xm0_io0")
            tNodeParam = ElementTree.SubElement(tNodePeripheralConfig, 'parameter')
            tNodeParam.set('id', 'xm0_io0')
            tNodeParam.set('value', 'enabled')

            # Optional: formatting
            tNodeParam1 = tNodePeripheralConfig.find(".//parameter[@id='hw_option']")
            if tNodeParam1 is not None:
                tNodeParam.tail = tNodeParam1.tail
                tNodeParam1.tail = tNodePeripheralConfig.text
            
            # Delete pin in io_config: <pin id="MII0_TXD1" peripheral="xm0" function="xm0_io1"/>
            tNodeIoConfigPin = tNodeIoConfig.find(".//pin[@id='MII0_TXD1'][@function='xm0_io1']")
            if tNodeIoConfigPin is not None:
                logging.debug("Removing xm0_io1 from io_config")
                tNodeIoConfig.remove(tNodeIoConfigPin)
                
            # Delete pin in pad_config: <pin id="MII0_TXD1" drive_strength="low" pull_enable="true"/>
            tNodePadConfigPin = tNodePadConfig.find(".//pin[@id='MII0_TXD1']")
            if tNodePadConfigPin is not None:
                logging.debug("Removing xm0_io1 from pad_config")
                tNodePadConfig.remove(tNodePadConfigPin)
            
            fUpdated = True
        return fUpdated
            
# Pinning XML file (pinning + peripherals definitions for netx Studio)
# A dummy implementation just to read the chip type/version information 
class Pinning:
    __strChiptypes = None
    __strBoards = None
    __strVersion = None
    __astrChiptypes = None
    __astrBoards = None
    
    def __init__(self):
        logging.debug('Created a new Pinning instance.')

    def get_version(self):
        return self.__strVersion
        
    def get_chiptypes_str(self):
        return self.__strChiptypes

    def get_chiptypes(self):
        return self.__astrChiptypes

    def get_boards_str(self):
        return self.__strBoards

    def get_boards(self):
        return self.__astrBoards

    def get_peripheral_ids(self):
        astrPeripheralIds = []
        tNodeRoot = self.__tXmlRoot 
        atNodePeripherals = tNodeRoot.findall('.peripheral_categories//peripheral')
        
        for tNodePer in atNodePeripherals:
            strId = tNodePer.text
            astrPeripheralIds.append(strId)
            
        return astrPeripheralIds    
        
    def read(self, strInputPath):
        logging.debug('Reading the pinning definition from "%s".' % strInputPath)

        tFile = open(strInputPath, 'rt')
        strXml = tFile.read()
        tFile.close()
        tXmlRoot = ElementTree.fromstring(strXml)
        self.__tXmlRoot = tXmlRoot

        # Get the chiptype and version attributes.
        if 'chip_type' not in tXmlRoot.attrib:
            raise Exception('Missing attribute "chip_type"')
        elif 'version' not in tXmlRoot.attrib:
            raise Exception('Missing attribute "version"')
        elif 'board' not in tXmlRoot.attrib:
            raise Exception('Missing attribute "board"')
        else:
            self.__strChiptypes = tXmlRoot.attrib['chip_type']
            self.__strBoards = tXmlRoot.attrib['board']
            self.__strVersion = tXmlRoot.attrib['version']
            self.__astrChiptypes = self.__strChiptypes.split(",")
            self.__astrBoards = self.__strBoards.split(",")


            
class Peripherals:
    # chiptype and version attributes from peripherals.xml
    __strChiptypes = None
#    __strBoards = None
    __strVersion = None
    __astrChiptypes = None
#    __astrBoards = None
    
    # tool_version attribute from the HWconfig.xml file (netx Studio)
    __strHwConfigDocVersion = None
    __strHwConfigChipType = None

    __tXmlRoot = None
    __atRegisters = None
    __atIoConfigurations = None
    __atPeripherals = None
    __atAffectedPins = None
    __atConstraints = None
    __strTemplate = None

    # Translate the name from pad_config/pin/@id to a valid pad_ctrl register name.
    # Note: the registers must be ordered by address. 
    __atPadCtrlRegisters = [
        {'id': 'RDY_N',                   'path': 'register/pad_ctrl/pad_ctrl_rdy_n'},
        {'id': 'RUN_N',                   'path': 'register/pad_ctrl/pad_ctrl_run_n'},
        {'id': 'MLED0',                   'path': 'register/pad_ctrl/pad_ctrl_mled0'},
        {'id': 'MLED1',                   'path': 'register/pad_ctrl/pad_ctrl_mled1'},
        {'id': 'MLED2',                   'path': 'register/pad_ctrl/pad_ctrl_mled2'},
        {'id': 'MLED3',                   'path': 'register/pad_ctrl/pad_ctrl_mled3'},
        {'id': 'COM_IO0',                 'path': 'register/pad_ctrl/pad_ctrl_com_io0'},
        {'id': 'COM_IO1',                 'path': 'register/pad_ctrl/pad_ctrl_com_io1'},
        {'id': 'COM_IO2',                 'path': 'register/pad_ctrl/pad_ctrl_com_io2'},
        {'id': 'COM_IO3',                 'path': 'register/pad_ctrl/pad_ctrl_com_io3'},
        
        {'id': 'UART_RXD',                'path': 'register/pad_ctrl/pad_ctrl_uart_rxd'},
        {'id': 'UART_TXD',                'path': 'register/pad_ctrl/pad_ctrl_uart_txd'},
        
        {'id': 'MII0_RXCLK',              'path': 'register/pad_ctrl/pad_ctrl_mii0_rxclk'},
        {'id': 'MII0_RXD0',               'path': 'register/pad_ctrl/pad_ctrl_mii0_rxd0'},
        {'id': 'MII0_RXD1',               'path': 'register/pad_ctrl/pad_ctrl_mii0_rxd1'},
        {'id': 'MII0_RXD2',               'path': 'register/pad_ctrl/pad_ctrl_mii0_rxd2'},
        {'id': 'MII0_RXD3',               'path': 'register/pad_ctrl/pad_ctrl_mii0_rxd3'},
        {'id': 'MII0_RXDV',               'path': 'register/pad_ctrl/pad_ctrl_mii0_rxdv'},
        {'id': 'MII0_RXER',               'path': 'register/pad_ctrl/pad_ctrl_mii0_rxer'},
        {'id': 'MII0_TXCLK',              'path': 'register/pad_ctrl/pad_ctrl_mii0_txclk'},
        {'id': 'MII0_TXD0',               'path': 'register/pad_ctrl/pad_ctrl_mii0_txd0'},
        {'id': 'MII0_TXD1',               'path': 'register/pad_ctrl/pad_ctrl_mii0_txd1'},
        {'id': 'MII0_TXD2',               'path': 'register/pad_ctrl/pad_ctrl_mii0_txd2'},
        {'id': 'MII0_TXD3',               'path': 'register/pad_ctrl/pad_ctrl_mii0_txd3'},
        {'id': 'MII0_TXEN',               'path': 'register/pad_ctrl/pad_ctrl_mii0_txen'},
        {'id': 'MII0_COL',                'path': 'register/pad_ctrl/pad_ctrl_mii0_col'},
        {'id': 'MII0_CRS',                'path': 'register/pad_ctrl/pad_ctrl_mii0_crs'},
        {'id': 'PHY0_LED_LINK_IN',        'path': 'register/pad_ctrl/pad_ctrl_phy0_led_link_in'},
        {'id': 'MII1_RXCLK',              'path': 'register/pad_ctrl/pad_ctrl_mii1_rxclk'},
        {'id': 'MII1_RXD0',               'path': 'register/pad_ctrl/pad_ctrl_mii1_rxd0'},
        {'id': 'MII1_RXD1',               'path': 'register/pad_ctrl/pad_ctrl_mii1_rxd1'},
        {'id': 'MII1_RXD2',               'path': 'register/pad_ctrl/pad_ctrl_mii1_rxd2'},
        {'id': 'MII1_RXD3',               'path': 'register/pad_ctrl/pad_ctrl_mii1_rxd3'},
        {'id': 'MII1_RXDV',               'path': 'register/pad_ctrl/pad_ctrl_mii1_rxdv'},
        {'id': 'MII1_RXER',               'path': 'register/pad_ctrl/pad_ctrl_mii1_rxer'},
        {'id': 'MII1_TXCLK',              'path': 'register/pad_ctrl/pad_ctrl_mii1_txclk'},
        {'id': 'MII1_TXD0',               'path': 'register/pad_ctrl/pad_ctrl_mii1_txd0'},
        {'id': 'MII1_TXD1',               'path': 'register/pad_ctrl/pad_ctrl_mii1_txd1'},
        {'id': 'MII1_TXD2',               'path': 'register/pad_ctrl/pad_ctrl_mii1_txd2'},
        {'id': 'MII1_TXD3',               'path': 'register/pad_ctrl/pad_ctrl_mii1_txd3'},
        {'id': 'MII1_TXEN',               'path': 'register/pad_ctrl/pad_ctrl_mii1_txen'},
        {'id': 'MII1_COL',                'path': 'register/pad_ctrl/pad_ctrl_mii1_col'},
        {'id': 'MII1_CRS',                'path': 'register/pad_ctrl/pad_ctrl_mii1_crs'},
        {'id': 'PHY1_LED_LINK_IN',        'path': 'register/pad_ctrl/pad_ctrl_phy1_led_link_in'},
        {'id': 'MII_MDC',                 'path': 'register/pad_ctrl/pad_ctrl_mii_mdc'},
        {'id': 'MII_MDIO',                'path': 'register/pad_ctrl/pad_ctrl_mii_mdio'},
        {'id': 'RST_OUT_N',               'path': 'register/pad_ctrl/pad_ctrl_rst_out_n'},
        {'id': 'CLK25OUT',                'path': 'register/pad_ctrl/pad_ctrl_clk25out'},
        
        {'id': 'MII0_TXEN_BGA2',          'path': 'register/pad_ctrl/pad_ctrl_mii0_txen_bga2'},
        {'id': 'MII0_COL_BGA2',           'path': 'register/pad_ctrl/pad_ctrl_mii0_col_bga2'},
        {'id': 'MII0_CRS_BGA2',           'path': 'register/pad_ctrl/pad_ctrl_mii0_crs_bga2'},
        {'id': 'PHY0_LED_LINK_IN_BGA2',   'path': 'register/pad_ctrl/pad_ctrl_phy0_led_link_in_bga2'},
        {'id': 'MII1_RXER_BGA2',          'path': 'register/pad_ctrl/pad_ctrl_mii1_rxer_bga2'},
        {'id': 'MII1_COL_BGA2',           'path': 'register/pad_ctrl/pad_ctrl_mii1_col_bga2'},
        {'id': 'MII1_CRS_BGA2',           'path': 'register/pad_ctrl/pad_ctrl_mii1_crs_bga2'},
        {'id': 'PHY1_LED_LINK_IN_BGA2',   'path': 'register/pad_ctrl/pad_ctrl_phy1_led_link_in_bga2'},
        
        {'id': 'MMIO0',                   'path': 'register/pad_ctrl/pad_ctrl_mmio0'},
        {'id': 'MMIO1',                   'path': 'register/pad_ctrl/pad_ctrl_mmio1'},
        {'id': 'MMIO2',                   'path': 'register/pad_ctrl/pad_ctrl_mmio2'},
        {'id': 'MMIO3',                   'path': 'register/pad_ctrl/pad_ctrl_mmio3'},
        {'id': 'MMIO4',                   'path': 'register/pad_ctrl/pad_ctrl_mmio4'},
        {'id': 'MMIO5',                   'path': 'register/pad_ctrl/pad_ctrl_mmio5'},
        {'id': 'MMIO6',                   'path': 'register/pad_ctrl/pad_ctrl_mmio6'},
        {'id': 'MMIO7',                   'path': 'register/pad_ctrl/pad_ctrl_mmio7'},
        {'id': 'SQI_CLK',                 'path': 'register/pad_ctrl/pad_ctrl_sqi_clk'},
        {'id': 'SQI_CS0N',                'path': 'register/pad_ctrl/pad_ctrl_sqi_cs0n'},
        {'id': 'SQI_MOSI',                'path': 'register/pad_ctrl/pad_ctrl_sqi_mosi'},
        {'id': 'SQI_MISO',                'path': 'register/pad_ctrl/pad_ctrl_sqi_miso'},
        {'id': 'SQI_SIO2',                'path': 'register/pad_ctrl/pad_ctrl_sqi_sio2'},
        {'id': 'SQI_SIO3',                'path': 'register/pad_ctrl/pad_ctrl_sqi_sio3'},
        {'id': 'HIF_A0',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a0'},
        {'id': 'HIF_A1',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a1'},
        {'id': 'HIF_A2',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a2'},
        {'id': 'HIF_A3',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a3'},
        {'id': 'HIF_A4',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a4'},
        {'id': 'HIF_A5',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a5'},
        {'id': 'HIF_A6',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a6'},
        {'id': 'HIF_A7',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a7'},
        {'id': 'HIF_A8',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a8'},
        {'id': 'HIF_A9',                  'path': 'register/pad_ctrl/pad_ctrl_hif_a9'},
        {'id': 'HIF_A10',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a10'},
        {'id': 'HIF_A11',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a11'},
        {'id': 'HIF_A12',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a12'},
        {'id': 'HIF_A13',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a13'},
        {'id': 'HIF_A14',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a14'},
        {'id': 'HIF_A15',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a15'},
        {'id': 'HIF_A16',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a16'},
        {'id': 'HIF_A17',                 'path': 'register/pad_ctrl/pad_ctrl_hif_a17'},
        {'id': 'HIF_D0',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d0'},
        {'id': 'HIF_D1',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d1'},
        {'id': 'HIF_D2',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d2'},
        {'id': 'HIF_D3',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d3'},
        {'id': 'HIF_D4',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d4'},
        {'id': 'HIF_D5',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d5'},
        {'id': 'HIF_D6',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d6'},
        {'id': 'HIF_D7',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d7'},
        {'id': 'HIF_D8',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d8'},
        {'id': 'HIF_D9',                  'path': 'register/pad_ctrl/pad_ctrl_hif_d9'},
        {'id': 'HIF_D10',                 'path': 'register/pad_ctrl/pad_ctrl_hif_d10'},
        {'id': 'HIF_D11',                 'path': 'register/pad_ctrl/pad_ctrl_hif_d11'},
        {'id': 'HIF_D12',                 'path': 'register/pad_ctrl/pad_ctrl_hif_d12'},
        {'id': 'HIF_D13',                 'path': 'register/pad_ctrl/pad_ctrl_hif_d13'},
        {'id': 'HIF_D14',                 'path': 'register/pad_ctrl/pad_ctrl_hif_d14'},
        {'id': 'HIF_D15',                 'path': 'register/pad_ctrl/pad_ctrl_hif_d15'},
        {'id': 'HIF_BHEN',                'path': 'register/pad_ctrl/pad_ctrl_hif_bhen'},
        {'id': 'HIF_CSN',                 'path': 'register/pad_ctrl/pad_ctrl_hif_csn'},
        {'id': 'HIF_RDN',                 'path': 'register/pad_ctrl/pad_ctrl_hif_rdn'},
        {'id': 'HIF_WRN',                 'path': 'register/pad_ctrl/pad_ctrl_hif_wrn'},
        {'id': 'HIF_RDY',                 'path': 'register/pad_ctrl/pad_ctrl_hif_rdy'},
        {'id': 'HIF_DIRQ',                'path': 'register/pad_ctrl/pad_ctrl_hif_dirq'},
        {'id': 'HIF_SDCLK',               'path': 'register/pad_ctrl/pad_ctrl_hif_sdclk'},
    ]

    __atMmioRegisters = {
        'MMIO0': 'register/mmio_ctrl/mmio0_cfg',
        'MMIO1': 'register/mmio_ctrl/mmio1_cfg',
        'MMIO2': 'register/mmio_ctrl/mmio2_cfg',
        'MMIO3': 'register/mmio_ctrl/mmio3_cfg',
        'MMIO4': 'register/mmio_ctrl/mmio4_cfg',
        'MMIO5': 'register/mmio_ctrl/mmio5_cfg',
        'MMIO6': 'register/mmio_ctrl/mmio6_cfg',
        'MMIO7': 'register/mmio_ctrl/mmio7_cfg',
        'MMIO8': 'register/mmio_ctrl/mmio8_cfg',
        'MMIO9': 'register/mmio_ctrl/mmio9_cfg',
        'MMIO10': 'register/mmio_ctrl/mmio10_cfg',
        'MMIO11': 'register/mmio_ctrl/mmio11_cfg',
        'MMIO12': 'register/mmio_ctrl/mmio12_cfg',
        'MMIO13': 'register/mmio_ctrl/mmio13_cfg',
        'MMIO14': 'register/mmio_ctrl/mmio14_cfg',
        'MMIO15': 'register/mmio_ctrl/mmio15_cfg',
        'MMIO16': 'register/mmio_ctrl/mmio16_cfg',
        'MMIO17': 'register/mmio_ctrl/mmio17_cfg',
    }

    __atMmioSignals = {
        'XC_SAMPLE0' :          0,
        'XC_SAMPLE1' :          1,
        'XC_TRIGGER0' :         2,
        'XC_TRIGGER1' :         3,
        'CAN0_APP_RX' :         4,
        'CAN0_APP_TX' :         5,
        'CAN1_APP_RX' :         6,
        'CAN1_APP_TX' :         7,
        'I2C_XPIC_APP_SCL' :    8,
        'I2C_XPIC_APP_SDA' :    9,
        'I2C_APP_SCL' :         10,
        'I2C_APP_SDA' :         11,
        'SPI_XPIC_APP_CLK' :    12,
        'SPI_XPIC_APP_CS0N' :   13,
        'SPI_XPIC_APP_CS1N' :   14,
        'SPI_XPIC_APP_CS2N' :   15,
        'SPI_XPIC_APP_MISO' :   16,
        'SPI_XPIC_APP_MOSI' :   17,
        'SPI1_APP_CLK' :        18,
        'SPI1_APP_CS0N' :       19,
        'SPI1_APP_CS1N' :       20,
        'SPI1_APP_CS2N' :       21,
        'SPI1_APP_MISO' :       22,
        'SPI1_APP_MOSI' :       23,
        'UART_XPIC_APP_RXD' :   24,
        'UART_XPIC_APP_TXD' :   25,
        'UART_XPIC_APP_RTSN' :  26,
        'UART_XPIC_APP_CTSN' :  27,
        'UART_APP_RXD' :        28,
        'UART_APP_TXD' :        29,
        'UART_APP_RTSN' :       30,
        'UART_APP_CTSN' :       31,
        'GPIO0' :               32,
        'GPIO1' :               33,
        'GPIO2' :               34,
        'GPIO3' :               35,
        'GPIO4' :               36,
        'GPIO5' :               37,
        'GPIO6' :               38,
        'GPIO7' :               39,
        'WDG_ACT' :             40,
        'EN_IN' :               41,
        'ETH_MDC' :             42,
        'ETH_MDIO' :            43,
        'PIO':                  63,
    }

    def __init__(self):
        logging.debug('Created a new Peripherals instance.')
        # All pins are free by default.
        self.__atAffectedPins = {}

    def get_version(self):
        return self.__strVersion
        
    def get_chiptypes_str(self):
        return self.__strChiptypes
        
    def get_chiptypes(self):
        return self.__astrChiptypes

#    def get_boards_str(self):
#        return self.__strBoards
#
#    def get_boards(self):
#        return self.__astrBoards

    def set_hwconfig_doc_version(self, strDocVersion):
        self.__strHwConfigDocVersion = strDocVersion
        
    def get_hwconfig_doc_version(self):
        return self.__strHwConfigDocVersion
        
    def set_hwconfig_chip_type(self, strChipType):
        self.__strHwConfigChipType = strChipType
        
    def get_hwconfig_chip_type(self):
        return self.__strHwConfigChipType
        
        
    def __parse_ioconfig_register_values(self, tNodeIoConfig):
        atRegisterValues = {}
        for tNodeRegisterValue in tNodeIoConfig.findall('RegisterValue'):
            # The "path" attribute is required.
            if 'path' not in tNodeRegisterValue.attrib:
                logging.error('Missing attribute "path" in register value definition.')
                raise Exception('invalid peripheral definition.')
            strPath = tNodeRegisterValue.attrib['path']
            # The "value" attribute is required.
            if 'value' not in tNodeRegisterValue.attrib:
                logging.error('Missing attribute "value" in register value definition.')
                raise Exception('invalid peripheral definition.')
            strValue = tNodeRegisterValue.attrib['value']
            try:
                ulValue = int(strValue, 0)
            except ValueError:
                raise Exception('Invalid value "%s" for register "%s".' % (strValue, strPath))

            if strPath in atRegisterValues:
                raise Exception('Register "%s" assigned multiple times.' % strPath)

            atRegisterValues[strPath] = ulValue

        return atRegisterValues

    def __parse_ioconfig_affected_pins(self, tNodeIoConfig):
        atAffectedPins = {}
        for tNodeAffectedPin in tNodeIoConfig.findall('AffectedPin'):
            # The "id" attribute is required.
            if 'id' not in tNodeAffectedPin.attrib:
                logging.error('Missing attribute "id" in affected pin definition.')
                raise Exception('invalid peripheral definition.')
            strID = tNodeAffectedPin.attrib['id']
            # The "value" attribute is required.
            if 'value' not in tNodeAffectedPin.attrib:
                logging.error('Missing attribute "value" in affected pin definition.')
                raise Exception('invalid peripheral definition.')
            strValue = tNodeAffectedPin.attrib['value']

            if strID in atAffectedPins:
                raise Exception('Affected pin "%s" is present multiple times.' % strID)

            atAffectedPins[strID] = strValue

        return atAffectedPins

    def read(self, strInputPath):
        logging.debug('Reading the peripherals definition from "%s".' % strInputPath)

        if os.path.isfile(strInputPath):
            tFile = open(strInputPath, 'rt')
        else:
            path = os.path.join(os.path.dirname(os.path.realpath(__file__)), strInputPath)
            tFile = open(path, 'rt')

        strXml = tFile.read()
        tFile.close()
        tXmlRoot = ElementTree.fromstring(strXml)
        self.__tXmlRoot = tXmlRoot

        # Get the chiptype and version attributes.
        if 'chip' not in tXmlRoot.attrib:
            raise Exception('Missing attribute "chip"')
        elif 'version' not in tXmlRoot.attrib:
            raise Exception('Missing attribute "version"')
#        elif 'board' not in tXmlRoot.attrib:
#            raise Exception('Missing attribute "board"')
        else:
            self.__strVersion = tXmlRoot.attrib['version']
#            self.__strBoards = tXmlRoot.attrib['board']
            self.__strChiptypes = tXmlRoot.attrib['chip']
#            self.__astrBoards = self.__strBoards.split(",")
            self.__astrChiptypes = self.__strChiptypes.split(",")

        # Parse all registers.
        atRegisters = {}
        for tNodeRegister in tXmlRoot.findall('Registers/Register'):
            # The "path" attribute is required.
            if 'path' not in tNodeRegister.attrib:
                logging.error('Missing attribute "path" in register definition.')
                raise Exception('invalid peripheral definition.')
            strPath = tNodeRegister.attrib['path']
            if strPath in atRegisters:
                raise Exception('The register "%s" is already defined.' % strPath)

            # Collect all bitfields.
            atRegister = {}
            atBitfields = {}
            atRegister['bitfields'] = atBitfields
            atRegister['path'] = strPath
            for tNodeBitfield in tNodeRegister.findall('Bitfield'):
                fAllOK = True
                # The id attribute is required.
                if 'id' not in tNodeBitfield.attrib:
                    logging.error('Missing attribute "id" in bitfield definition.')
                    fAllOK = False
                else:
                    strID = tNodeBitfield.attrib['id']
                if strID in atBitfields:
                    logging.error('The bitfield "%s" is already defined.' % strID)
                    fAllOK = False

                if 'start' not in tNodeBitfield.attrib:
                    logging.error('Missing attribute "start" in bitfield definition.')
                    fAllOK = False
                else:
                    try:
                        ulStart = int(tNodeBitfield.attrib['start'], 0)
                    except ValueError:
                        logging.error('Attribute "start" in bitfield definition is no number.')
                        fAllOK = False

                if 'width' not in tNodeBitfield.attrib:
                    logging.error('Missing attribute "width" in bitfield definition.')
                    fAllOK = False
                else:
                    try:
                        ulWidth = int(tNodeBitfield.attrib['width'], 0)
                    except ValueError:
                        logging.error('Attribute "width" in bitfield definition is no number.')
                        fAllOK = False

                if 'default' not in tNodeBitfield.attrib:
                    logging.error('Missing attribute "default" in bitfield definition.')
                    fAllOK = False
                else:
                    try:
                        ulDefault = int(tNodeBitfield.attrib['default'], 0)
                    except ValueError:
                        logging.error('Attribute "default" in bitfield definition is no number.')
                        fAllOK = False

                if fAllOK is not True:
                    raise Exception('Invalid peripheral definition.')

                atBitfield = {}
                atBitfield['path'] = strPath
                atBitfield['id'] = strID
                atBitfield['start'] = ulStart
                atBitfield['width'] = ulWidth
                atBitfield['default'] = ulDefault
                atBitfield['value'] = None
                atBitfield['owner'] = None

                atBitfields[strID] = atBitfield
            atRegisters[strPath] = atRegister

        self.__atRegisters = atRegisters

        # Parse all IO configurations.
        atIoConfigurations = {}
        for tNodeIoConfig in tXmlRoot.findall('IoConfigurations/IoConfig'):
            # The "id" attribute is required.
            if 'id' not in tNodeIoConfig.attrib:
                logging.error('Missing attribute "id" in IoConfig definition.')
                raise Exception('invalid peripheral definition.')
            strID = tNodeIoConfig.attrib['id']
            if strID in atIoConfigurations:
                logging.error('The IoConfig "%s" is already defined.' % strID)
                raise Exception('invalid peripheral definition.')

            atIoConfig = {}
            atIoConfig['register_values'] = self.__parse_ioconfig_register_values(tNodeIoConfig)
            atIoConfig['affected_pins'] = self.__parse_ioconfig_affected_pins(tNodeIoConfig)

            atIoConfigurations[strID] = atIoConfig

        self.__atIoConfigurations = atIoConfigurations

        # Read all peripherals.
        atPeripherals = {}
        for tNodePeripheral in tXmlRoot.findall('Peripherals/Peripheral'):
            # The "id" attribute is required.
            if 'id' not in tNodePeripheral.attrib:
                logging.error('Missing attribute "id" in Peripheral definition.')
                raise Exception('invalid peripheral definition.')
            strID = tNodePeripheral.attrib['id']
            if strID in atPeripherals:
                logging.error('The peripheral "%s" is already defined.' % strID)
                raise Exception('invalid peripheral definition.')

            atPeripheral = {}
            atPeripheral['code'] = tNodePeripheral.text

            atPeripherals[strID] = atPeripheral

        self.__atPeripherals = atPeripherals

        # Read all constraints.
        atConstraints = {}
        for tNodeConstraint in tXmlRoot.findall('Constraints/Constraint'):
            # The "id" attribute is required.
            if 'id' not in tNodeConstraint.attrib:
                logging.error('Missing attribute "id" in constraint definition.')
                raise Exception('invalid peripheral definition.')
            strID = tNodeConstraint.attrib['id']
            if strID in atConstraints:
                logging.error('The constraint "%s" is already defined.' % strID)
                raise Exception('invalid peripheral definition.')

            atConstraint = {}

            # Get the description.
            tNodeDescription = tNodeConstraint.find('Description')
            if tNodeDescription is None:
                logging.error('Missing node "Description" in constraint definition.')
                raise Exception('invalid peripheral definition.')
            atConstraint['description'] = tNodeDescription.text

            # Get the code.
            tNodeCode = tNodeConstraint.find('Code')
            if tNodeCode is None:
                logging.error('Missing node "Code" in constraint definition.')
                raise Exception('invalid peripheral definition.')
            atConstraint['code'] = tNodeCode.text

            atConstraints[strID] = atConstraint

        self.__atConstraints = atConstraints

        # Read the template.
        tNodeTemplate = tXmlRoot.find('Template')
        if tNodeTemplate is None:
            raise Exception('No "Template" node found.')
        self.__strTemplate = tNodeTemplate.text.strip()

    def __bitfield_get_value(self, atBitfield, bOnlyDefaults=False):
        strPath = atBitfield['path']
        strBitfield = atBitfield['id']

        if bOnlyDefaults is True:
            ulBitfieldValue = atBitfield['default']
        else:
            # Use the value if something is already assigned.
            ulBitfieldValue = atBitfield['value']
            if ulBitfieldValue is None:
                ulBitfieldValue = atBitfield['default']

        # Get the start and width fields.
        ulBitfieldWidth = atBitfield['width']

        # The value must fit into the bitfield.
        if ulBitfieldValue >= pow(2, ulBitfieldWidth):
            raise Exception('The value 0x%08x exceeds the bitfield %s of register %s.' % (ulBitfieldValue, strBitfield, strPath))

        return ulBitfieldValue

    def __register_get_value(self, atRegister, bOnlyDefaults=False):
        ulRegisterValue = 0

        # Loop over all bitfields in the register.
        for strBitfield, atBitfield in atRegister['bitfields'].items():
            ulBitfieldValue = self.__bitfield_get_value(atBitfield, bOnlyDefaults)

            # Get the start and width fields.
            ulBitfieldStart = atBitfield['start']
            ulBitfieldWidth = atBitfield['width']

            # Generate the mask for the bitfield.
            ulMask = (pow(2, ulBitfieldWidth) - 1) << ulBitfieldStart

            # The register value should be 0 at the position of the bitfield.
            # Combine the register value with the bitfield.
            if (ulRegisterValue & ulMask) != 0:
                raise Exception('Merging bitfield %s to an already used register area!' % strBitfield)

            ulRegisterValue |= ulBitfieldValue << ulBitfieldStart

        return ulRegisterValue

    def __bitfield_set_value(self, atBitfield, ulValue, strOwner):
        # Be pessimistic.
        fResult = False

        strBitfieldID = '%s/%s' % (atBitfield['path'], atBitfield['id'])

        if (atBitfield['value'] is not None) or (atBitfield['owner'] is not None):
            logging.error('The bitfield "%s" is already set by "%s".' % (strBitfieldID, atBitfield['owner']))

        else:
            # The value must fit into the bitfield.
            ulBitfieldWidth = atBitfield['width']
            if ulValue >= pow(2, ulBitfieldWidth):
                logging.error('Trying to set the bitfield "%s/%s" to a too large value of 0x%08x.' % (strBitfieldID, ulValue))
            else:
                logging.debug('Setting bitfield "%s" to 0x%08x from owner "%s".' % (strBitfieldID, ulValue, strOwner))
                atBitfield['value'] = ulValue
                atBitfield['owner'] = strOwner

                fResult = True

        return fResult

    def __register_set_value(self, atRegister, ulValue, strOwner):
        fResult = True

        # Collect all masks to check the reserved bits.
        ulCompleteMask = 0

        # Loop over all bitfields.
        for strBitfield, atBitfield in atRegister['bitfields'].items():
            # Get the start and width fields.
            ulBitfieldStart = atBitfield['start']
            ulBitfieldWidth = atBitfield['width']

            # Generate the mask for the bitfield.
            ulMask = pow(2, ulBitfieldWidth) - 1

            # Extract the bitfield part of the complete register value.
            ulValueBitfield = (ulValue >> ulBitfieldStart) & ulMask
            fResult = self.__bitfield_set_value(atBitfield, ulValueBitfield, strOwner)
            if fResult is not True:
                break

            # Add the mask.
            ulCompleteMask |= ulMask << ulBitfieldStart

        # ulCompleteMask contains now all processed bits.
        # Check if not processed bits are non 0.
        ulReservedMask = ulCompleteMask ^ 0xffffffff
        if (ulValue & ulReservedMask) != 0:
            logging.error('The value 0x%08x for register %s has non 0 bits in the reserved fields: 0x%08x' % (ulValue, atRegister['path'], ulValue & ulReservedMask))
            fResult = False

        return fResult

    def get_register(self, strPath):
        atRegister = None
        # Does the path point to a register?
        if strPath in self.__atRegisters:
            atRegister = self.__atRegisters[strPath]
        return atRegister

    def register_path_set_value(self, strPath, ulValue, strOwner):
        # Does the path point to a register?
        if strPath in self.__atRegisters:
            # Yes, this is a register. Set all bitfields from the value.
            atRegister = self.__atRegisters[strPath]
            fResult = self.__register_set_value(atRegister, ulValue, strOwner)
            if fResult is not True:
                raise Exception('Failed to set the register "%s" to value 0x%08x.' % (strPath, ulValue))
        else:
            # Does the path point to a bitfield?
            strPathRegister, strPathBitfield = os.path.split(strPath)
            if strPathRegister in self.__atRegisters:
                atRegister = self.__atRegisters[strPathRegister]
                # Does the bitfield exist?
                atBitfields = atRegister['bitfields']
                if strPathBitfield in atBitfields:
                    atBitfield = atBitfields[strPathBitfield]
                    fResult = self.__bitfield_set_value(atBitfield, ulValue, strOwner)
                    if fResult is not True:
                        raise Exception('Failed to set bitfield "%s" of register "%s" to value 0x%08x.' % (strPathBitfield, strPathRegister, ulValue))
                else:
                    raise Exception('The register "%s" does not have a bitfield named "%s".' % (strPathRegister, strPathBitfield))
            else:
                raise Exception('The path "%s" does not point to a register or a bitfield.' % strPath)

    # Allow setting a register/bit field multiple times if the value is the same.
    # Check if the register/bit field is already set (i.e. it has an owner). 
    # If not, set it as usual.
    # If it has already been set, compare the current value to the new one. 
    # If they differ, raise an error. If they are equal, do nothing.
    def register_path_set_value_preowned(self, strPath, ulValue, strOwner):
        strExistingOwner = self.bitfield_get_owner(strPath)
        if strExistingOwner is None:
            # The register/bit field is not set yet. Do this now.
            self.register_path_set_value(strPath, ulValue, strOwner)
        else:
            # The register/bit field is already set. Compare the values.
            ulExistingValue = self.register_path_get_value(strPath)
            if ulExistingValue != ulValue:
                # The values differ. This is an error.
                raise Exception('register/bit field %s is already set to %d by %s.' % (strPath, ulExistingValue, strOwner))
    
    
    def register_path_get_value(self, strPath):
        # Does the path point to a register?
        if strPath in self.__atRegisters:
            # Yes, this is a register. Get the complete DWORD.
            atRegister = self.__atRegisters[strPath]
            ulValue = self.__register_get_value(atRegister)

        else:
            # Does the path point to a bitfield?
            strPathRegister, strPathBitfield = os.path.split(strPath)
            if strPathRegister in self.__atRegisters:
                atRegister = self.__atRegisters[strPathRegister]
                # Does the bitfield exist?
                atBitfields = atRegister['bitfields']
                if strPathBitfield in atBitfields:
                    atBitfield = atBitfields[strPathBitfield]
                    ulValue = self.__bitfield_get_value(atBitfield)

                else:
                    raise Exception('The register "%s" does not have a bitfield named "%s".' % (strPathRegister, strPathBitfield))
            else:
                raise Exception('The path "%s" does not point to a register or a bitfield.' % strPath)

        logging.debug('Register "%s" has the value 0x%08x.' % (strPath, ulValue))
        return ulValue

    def bitfield_get_owner(self, strPath):
        logging.debug('Get the owner of bitfield "%s".' % strPath)
        strOwner = None

        strPathRegister, strPathBitfield = os.path.split(strPath)
        if strPathRegister in self.__atRegisters:
            atRegister = self.__atRegisters[strPathRegister]
            # Does the bitfield exist?
            atBitfields = atRegister['bitfields']
            if strPathBitfield in atBitfields:
                atBitfield = atBitfields[strPathBitfield]
                strOwner = atBitfield['owner']
        else:
            raise Exception('The path "%s" does not point to a register or a bitfield.' % strPath)

        if strOwner is None:
            strMsg = 'no owner'
        else:
            strMsg = 'the owner "%s"' % strOwner
        logging.debug('Bitfield "%s" has %s.' % (strPath, strMsg))
        return strOwner

    def mmio_set_signal(self, strID, strSignal):
        # Get the path to the register.
        if strID not in self.__atMmioRegisters:
            raise Exception('Unknown ID in mmio_config: %s' % strID)
        strPath = self.__atMmioRegisters[strID]
        logging.debug('Translate mmio_config ID "%s" to path "%s".' % (strID, strPath))

        if strSignal != 'DEFAULT':
            if strSignal not in self.__atMmioSignals:
                raise Exception('Invalid signal for MMIO "%s": "%s".' % (strID, strSignal))

            # Create the owner from the type (mmio_config) and the ID.
            strOwner = 'mmio_config %s' % strID

            ulValue = self.__atMmioSignals[strSignal]
            self.register_path_set_value(strPath + '/mmio_sel', ulValue, strOwner)

    def set_pad_ctrl(self, strPadID, tDriveStrength, tPullEnable, tInputEnable):
        # Create the owner from the type (pad_ctrl) and the ID.
        strOwner = 'pad_ctrl %s' % strPadID

        # Get the path to the pad ctrl register.
        strPath = None
        for atPadCtrl in self.__atPadCtrlRegisters:
            if atPadCtrl['id'] == strPadID:
                strPath = atPadCtrl['path']
                break
        if strPath is None:
            raise Exception('Unknown ID in pad ctrl: %s' % strPadID)
        logging.debug('Translate pad ID "%s" to path "%s".' % (strPadID, strPath))

        # Is the drive_strength set?
        if tDriveStrength is not None:
            ulValue = None
            # The drive strength can be "low", "high" or "default".
            if tDriveStrength == 'low':
                # The value for "low" is 0.
                ulValue = 0
            elif tDriveStrength == 'high':
                # The value for "high" is 1.
                ulValue = 1
            elif tDriveStrength == 'default':
                # Do not change the value.
                ulValue = None
            else:
                # Invalid value.
                raise Exception('Invalid drive strenght specified for pin "%s": "%s"' % (strPadID, tDriveStrength))

            if ulValue is not None:
                self.register_path_set_value(strPath + '/ds', ulValue, strOwner)

        # Is the pull_enable set?
        if tPullEnable is not None:
            ulValue = None
            # The pull enable can be "false", "true" or "default".
            if tPullEnable == 'false':
                # The value for "false" is 0.
                ulValue = 0
            elif tPullEnable == 'true':
                # The value for "true" is 1.
                ulValue = 1
            elif tPullEnable == 'default':
                # Do not change the value.
                ulValue = None
            else:
                # Invalid value.
                raise Exception('Invalid pull enable specified for pin "%s": "%s"' % (strPadID, tPullEnable))

            if ulValue is not None:
                self.register_path_set_value(strPath + '/pe', ulValue, strOwner)

        # Is the input_enable set?
        if tInputEnable is not None:
            ulValue = None
            # The pull enable can be "false", "true" or "default".
            if tInputEnable == 'false':
                # The value for "false" is 0.
                ulValue = 0
            elif tInputEnable == 'true':
                # The value for "true" is 1.
                ulValue = 1
            elif tInputEnable == 'default':
                # Do not change the value.
                ulValue = None
            else:
                # Invalid value.
                raise Exception('Invalid input enable specified for pin "%s": "%s"' % (strPadID, tInputEnable))

            if ulValue is not None:
                self.register_path_set_value(strPath + '/ie', ulValue, strOwner)

    def dump_register(self, atRegister):
        strPath = atRegister['path']
        ulValue = self.__register_get_value(atRegister)
        ulDefaultValue = self.__register_get_value(atRegister, True)
        if ulValue == ulDefaultValue:
            print('    %s: 0x%08x' % (strPath, ulDefaultValue))
        else:
            print('    %s: 0x%08x (default=0x%08x)' % (strPath, ulValue, ulDefaultValue))
        for strBitfield, atBitfield in atRegister['bitfields'].items():
            strInfo = ''
            ulValue = atBitfield['value']
            if ulValue is not None:
                strInfo += ', value=%d' % atBitfield['value']
            strOwner = atBitfield['owner']
            if strOwner is not None:
                strInfo += ', owner=%s' % atBitfield['owner']
            print('        %s: [%d:%d] default=%d%s' % (strBitfield, atBitfield['start'], atBitfield['start']+atBitfield['width'], atBitfield['default'], strInfo))

    def dump_all_registers(self):
        print('Registers:')
        for strPath, atRegister in self.__atRegisters.items():
            self.dump_register(atRegister)

    # Print a peripheral configuration
    def show_parameters(self, atConfig, strConfigID):
        print('Config ID: "%s"' % strConfigID)
        for strKey, strValue in atConfig.items():
            print('    [%s] = %s' % (strKey, strValue))

    def set_affected_pin(self, strPin, strFunction):
        logging.debug('Setting pin "%s" to function "%s".' % (strPin, strFunction))

        # Is the pin already set?
        if strPin in self.__atAffectedPins:
            logging.error('Failed to set pin "%s" to function "%s". It is aready set to "%s".' % (strPin, strFunction, self.__atAffectedPins[strPin]))
            raise Exception('Pin %s is already in use!' % strPin)
        self.__atAffectedPins[strPin] = strFunction

    def apply_ioconfig(self, strID):
        # Does the IO configuration exist?
        if strID not in self.__atIoConfigurations:
            raise Exception('Unknown ioconfig "%s".' % strID)
        atIoConfig = self.__atIoConfigurations[strID]

        strOwner = 'ioconfig %s' % strID

        # Apply all register values.
        for strPath, ulValue in atIoConfig['register_values'].items():
            self.register_path_set_value(strPath, ulValue, strOwner)

        # Set all affected pins.
        for strPin, strFunction in atIoConfig['affected_pins'].items():
            self.set_affected_pin(strPin, strFunction)

    # if getParam_isEnabled(atConfig, 'dpm0_spi_dirq')
    # Read a required parameter whose value must be 'enabled' or 'disabled'.
    # If the parameter is missing or its value is neither 'enabled' or 'disabled',
    # raise an error.
    def getparam_isenabled(self, atConfig, strParamName):
        if strParamName in atConfig:
            strEnDis = atConfig[strParamName]
            if strEnDis == "enabled":
                return True
            elif strEnDis == "disabled":
                return False
            else: 
                raise Exception('The value of the config parameter %s must be either "enabled" or "disabled".' % strParamName)
        else:
            raise Exception('The mandatory config parameter %s is missing' % strParamName)

    # Read a required parameter whose value must be 'true' or 'false'.
    # If the parameter is missing or its value is neither 'true' or 'false',
    # raise an error.
    def getparam_bool(self, atConfig, strParamName):
        if strParamName in atConfig:
            strEnDis = atConfig[strParamName]
            if strEnDis == "true":
                return True
            elif strEnDis == "false":
                return False
            else: 
                raise Exception('The value of the config parameter %s must be either "true" or "false".' % strParamName)
        else:
            raise Exception('The mandatory config parameter %s is missing' % strParamName)

    def sandbox_api_apply_ioconfig(self, strID):
        logging.debug('sandbox API: apply_ioconfig %s' % strID)
        if not isinstance(strID, str):
            raise Exception('First argument of apply_ioconfig must be a string.')
        self.apply_ioconfig(strID)

    def sandbox_api_get_register(self, strRegister):
        logging.debug('sandbox API: get_register %s' % strRegister)
        if not isinstance(strRegister, str):
            raise Exception('First argument of get_register must be a string.')
        return self.register_path_get_value(strRegister)

    def sandbox_api_set_register(self, strRegister, ulValue, strOwner):
        logging.debug('sandbox API: set_register %s %s %s' % (strRegister, ulValue, strOwner))
        if not isinstance(strRegister, str):
            raise Exception('First argument of set_register must be a string.')
        if not isinstance(ulValue, int):
            raise Exception('Second argument of set_register must be a number.')
        if not isinstance(strOwner, str):
            raise Exception('Third argument of set_register must be a string.')
        self.register_path_set_value(strRegister, ulValue, strOwner)

    def sandbox_api_set_register_preowned(self, strRegister, ulValue, strOwner):
        logging.debug('sandbox API: sandbox_api_set_register_preowned %s %s %s' % (strRegister, ulValue, strOwner))
        if not isinstance(strRegister, str):
            raise Exception('First argument of sandbox_api_set_register_preowned must be a string.')
        if not isinstance(ulValue, int):
            raise Exception('Second argument of sandbox_api_set_register_preowned must be a number.')
        if not isinstance(strOwner, str):
            raise Exception('Third argument of sandbox_api_set_register_preowned must be a string.')
        self.register_path_set_value_preowned(strRegister, ulValue, strOwner)
        
    def sandbox_api_set_pin(self, strPin, strFunction):
        logging.debug('sandbox API: set_pin %s %s' % (strPin, strFunction))
        if not isinstance(strPin, str):
            raise Exception('First argument of set_pin must be a string.')
        if not isinstance(strFunction, str):
            raise Exception('Second argument of set_pin must be a string.')
        self.set_affected_pin(strPin, strFunction)

    def sandbox_api_get_owner(self, strRegister):
        logging.debug('sandbox API: get_owner %s' % strRegister)
        if not isinstance(strRegister, str):
            raise Exception('First argument of get_owner must be a string.')
        return self.bitfield_get_owner(strRegister)

    def __sandbox_api_get_parameter_is_enabled(self, atConfig, strParamName):
        logging.debug('sandbox API: getparam_isenabled %s' % strParamName)
        if not isinstance(atConfig, dict):
            raise Exception('First argument of get_parameter_is_enabled must be a dict.')
        if not isinstance(strParamName, str):
            raise Exception('Second argument of get_parameter_is_enabled must be a string.')
        return self.getparam_isenabled(atConfig, strParamName)

    def __sandbox_api_get_parameter_bool(self, atConfig, strParamName):
        logging.debug('sandbox API: getparam_bool %s' % strParamName)
        if not isinstance(atConfig, dict):
            raise Exception('First argument of get_parameter_bool must be a dict.')
        if not isinstance(strParamName, str):
            raise Exception('Second argument of get_parameter_bool must be a string.')
        return self.getparam_bool(atConfig, strParamName)

    def __sandbox_api_show_parameters(self, atConfig, strConfigID):
        logging.debug('sandbox API: show_parameters %s' % strConfigID)
        if not isinstance(atConfig, dict):
            raise Exception('First argument of show_parameters must be a dict.')
        if not isinstance(strConfigID, str):
            raise Exception('Second argument of show_parameters must be a string.')
        return self.show_parameters(atConfig, strConfigID)

    def __dump_sandbox_code(self, strCode):
        for strLine in strCode.split('\n'):
            logging.debug('SANDBOX CODE: %s' % strLine)

    def __run_sandbox_code(self, strCode, strFileID, atLocals={}):
        logging.debug('Running sandbox code:')
        self.__dump_sandbox_code(strCode)

        atGlobals = {
            'apply_ioconfig': self.sandbox_api_apply_ioconfig,
            'get_register': self.sandbox_api_get_register,
            'set_register': self.sandbox_api_set_register,
            'set_register_preowned': self.sandbox_api_set_register_preowned,
            'set_pin': self.sandbox_api_set_pin,
            'get_owner': self.sandbox_api_get_owner,
            'MMIO_SIGNALS': self.__atMmioSignals,
            'PAD_CTRL': self.__atPadCtrlRegisters,
            'getparam_isenabled': self.__sandbox_api_get_parameter_is_enabled,
            'getparam_bool': self.__sandbox_api_get_parameter_bool,
            'show_parameters': self.__sandbox_api_show_parameters,
            
            'PERIPHERALS_XML_CHIPTYPE':self.__strChiptypes, 
            'PERIPHERALS_XML_CHIPTYPES':self.__astrChiptypes, 
#            'PERIPHERALS_XML_BOARDS':self.__strBoards,
            'PERIPHERALS_XML_VERSION':self.__strVersion,
            'HWCONFIG_DOC_VERSION':self.__strHwConfigDocVersion,
            'HWCONFIG_TOOL_VERSION':hwconfig_tool_version_short,
            'HWCONFIG_CHIP_TYPE':self.__strHwConfigChipType,
        }
        tCode = compile(strCode, strFileID, 'exec')
        tResult = None
        strError = None
        try:
            exec(tCode, atGlobals, atLocals)
            tResult = True
        except Exception as e:
            strError = str(e)
            logging.debug('Failed to run sandbox code: %s' % strError)
            tResult = False

        return tResult, strError

    def apply_peripheral(self, strID, strConfigID, atConfig, atVerbatimNodes, strOwner):
        logging.debug('sandbox API: Apply peripheral "%s".' % strID)

        # Does the peripheral exist?
        if strID not in self.__atPeripherals:
            raise Exception('Unknown peripheral "%s".' % strID)
        atPeripheral = self.__atPeripherals[strID]

        # Get the config and config_id and provide it as locals.
        atLocals = {
            'atConfig': atConfig,
            'strConfigID': strConfigID,
            'atVerbatimNodes': atVerbatimNodes
        }

        # Get the code block and execute it.
        strCode = atPeripheral['code'].strip()
        strFileID = 'Peripheral code for %s' % strID
        tResult, strError = self.__run_sandbox_code(strCode, strFileID, atLocals)
        if tResult is not True:
            logging.error('Failed to apply peripheral "%s": %s' % (strID, strError))
            raise Exception('Invalid hardware configuration.')

    def apply_sdram_settings(self, ulSdramGeneralCtrl, ulSdramTimingCtrl, ulSdramModeRegister):
        strOwner = 'sdram_settings'
        self.register_path_set_value('register/hif_sdram_ctrl/sdram_general_ctrl', ulSdramGeneralCtrl, strOwner)
        self.register_path_set_value('register/hif_sdram_ctrl/sdram_timing_ctrl', ulSdramTimingCtrl, strOwner)
        self.register_path_set_value('register/hif_sdram_ctrl/sdram_mr', ulSdramModeRegister, strOwner)

    def check_constraints(self, tHwConfig):
        # Loop over all constraints.
        for strID, atConstraint in self.__atConstraints.items():
            logging.debug('Checking constraint "%s".' % strID)

            # Get the code block and execute it.
            strCode = atConstraint['code'].strip()
            strFileID = 'Constraint code for %s' % strID
            tResult, strError = self.__run_sandbox_code(strCode, strFileID)
            if tResult is not True:
                logging.error('Constraint "%s" failed: %s' % (strID, strError))
                raise Exception('Invalid hardware configuration.')

    def sandbox_api_output(self, strLine):
        self.__astrOutput.append(strLine)
        logging.debug('OUTPUT  %s' % strLine)

    def generate_template(self, strOutputFile):
        self.__astrOutput = []

        strFileID = 'Template code'
        atLocals = {
            'output': self.sandbox_api_output, 
            #'chip_type': strChipType
            }
        tResult, strError = self.__run_sandbox_code(self.__strTemplate, strFileID, atLocals)
        if tResult is not True:
            logging.error('Generating the template failed: %s' % (strError))
            raise Exception('Failed to generate the template.')

        # Write all generated lines to the output file.
        tFile = open(strOutputFile, 'wt')
        tFile.write('\n'.join(self.__astrOutput))
        tFile.close()


atLogLevels = {
    'critical': logging.CRITICAL,
    'error': logging.ERROR,
    'warning': logging.WARNING,
    'info': logging.INFO,
    'debug': logging.DEBUG
}


def parseVersionString(strVer):
    astrVer = strVer.split('.')
    aiVer = map(int, astrVer)
    return list(aiVer)
    
def make_hboot_xml(tArgs):
    logging.info(version_string)
    
    # Read the peripheral description.
    tPeripheral = Peripherals()
    tPeripheral.read(tArgs.strPeripheralsFile)
    
    # Read the hwconfig.
    tHwConfig = HwConfig()
    tHwConfig.set_peripherals(tPeripheral)
    tHwConfig.read_hwconfig(tArgs.strHwConfigFile)
    
    # Check the version of the hardware config.
    strCurVer = __revision__
    aiCurVer = parseVersionString(strCurVer)
    strHwcVer = tHwConfig.get_doc_version()
    aiHwcVer = parseVersionString(strHwcVer)
    if aiHwcVer < aiCurVer:
        raise Exception('The tool_version of the hardware config is older than the hwconfig tool (%s < %s). Try updating the hardware config.' % (strHwcVer, strCurVer))
    if aiHwcVer > aiCurVer:
        raise Exception('The tool_version of the hardware config is newer than the hwconfig tool (%s > %s). You need to update the hwconfig tool.' % (strHwcVer, strCurVer))
        
    tPeripheral.set_hwconfig_doc_version(tHwConfig.get_doc_version())
    tPeripheral.set_hwconfig_chip_type(tHwConfig.get_chip_type())
    
    tHwConfig.apply_pads()
    tHwConfig.apply_mmio_config()
    tHwConfig.apply_peripherals()
    tHwConfig.apply_sdram()
    
    tPeripheral.check_constraints(tHwConfig)
    
    tPeripheral.generate_template(tArgs.strOutputFile)



# chip types allowed on the command line
astrCmdLineChiptypes = ['netx90', 'netx90_rev0', 'netx90_rev1']
    
atKnownChips = [
    {'id':'netx90_rev0', 'name':'netX 90 Rev. 0'},
    {'id':'netx90_rev1', 'name':'netX 90 Rev. 1', 'id_alias':'netx90'},
]

atKnownBoards = [
    {'id':'nrp_h90-re_fxdx',  'name':'NRP H90-RE\FxDx'},
]

# The 'default' board represents the NXHX90-JTAG as well as custom boards.
atKnownCombos = [
    {
        'chip_id': 'netx90_rev0',
        'board_id': 'default',
        'gui': 'netx90.xml',
        'hwctool_peripherals': 'netx90_rev0_peripherals.xml'
    },
    {
        'chip_id': 'netx90_rev1',
        'board_id': 'default',
        'gui': 'netx90.xml',
        'hwctool_peripherals': 'netx90_rev1_peripherals.xml'
    },
    {
        'chip_id': 'netx90_rev1',
        'board_id': 'nrp_h90-re_fxdx',
        'gui': 'nrp_h90-re_fxdx.xml',
        'hwctool_peripherals': 'netx90_rev1_peripherals.xml'
    },
]



# Replace chip type alias netx90 -> netx90_rev1
def resolve_chip_type_alias(strChipType):
    for tChip in atKnownChips:
        if 'id_alias' in tChip and tChip['id_alias']==strChipType:
            strChipType = tChip['id']
            logging.info('Chip type %s mapped to %s' % (tChip['id_alias'], tChip['id']))
    return strChipType

def list_of_dict_to_xml(tDoc, tNodeParent, tList, strListTag, strEltTag):
    tNodeList = tDoc.createElement(strListTag)
    tNodeParent.appendChild(tNodeList)
    
    for tElt in tList:
        tNode = tDoc.createElement(strEltTag)
        tNodeList.appendChild(tNode)
        for (k, v) in tElt.iteritems():
            tNode.setAttribute(k, v)
        

# Example:
# print_list(atKnownChips,  'ChipTypes', ['id', 'name', 'id_alias'])
# with atKnownChips=[{'id':'netx90_rev0', 'name':'netX 90 Rev. 0'}]
# Output:   
# ChipTypes
# id: "netx90_rev0" name: "netX 90 Rev. 0"
def print_list_of_dict(tList, strName, astrFields):
    print(strName)
    for tEntry in tList:
        astrEntry = []
        for strField in astrFields:
            if strField in tEntry:
                strVal = '%s: "%s"' % (strField, str(tEntry[strField]))
                astrEntry.append(strVal)
        strEntry = " ".join(astrEntry)
        print(strEntry)
    print
    
def list_supported_targets(tArgs):
    # Path to this script
    this_path = os.path.realpath(__file__)
    
    # Directory of this script
    this_dir = os.path.dirname(this_path)
    
    # Add file version entries for the GUI files
    atFileVersions = {}
    for tCombo in atKnownCombos:
        strGuiXml = os.path.join(this_dir, tCombo['gui'])
        if strGuiXml in atFileVersions:
            tCombo['gui_version'] = atFileVersions[strGuiXml] 
        else:
            tPinning = Pinning()
            tPinning.read(strGuiXml)
            strVersion = tPinning.get_version()
            atFileVersions[strGuiXml] = strVersion
            tCombo['gui_version'] = strVersion 

    # List chip types, boards, chip/board combinations in a textual format
    # Print to console
    print_list_of_dict(atKnownChips,  'ChipTypes', ['id', 'name', 'id_alias'])
    print_list_of_dict(atKnownBoards, 'Boards',    ['id', 'name'])
    print_list_of_dict(atKnownCombos, 'Combos',    ['chip_id', 'board_id', 'gui', 'gui_version', 'hwctool_peripherals'])
    
    # Write in XML format to file strOutputFile, if specified
    tDoc = dom.Document()
    tNodeRoot = tDoc.createElement("supported_targets")
    tDoc.appendChild(tNodeRoot)

    list_of_dict_to_xml(tDoc, tNodeRoot, atKnownChips,  'chip_types', 'chip_type')
    list_of_dict_to_xml(tDoc, tNodeRoot, atKnownBoards, 'boards',     'board')
    list_of_dict_to_xml(tDoc, tNodeRoot, atKnownCombos, 'combos',     'combo')

    strPrettyXml = tDoc.toprettyxml()
    if tArgs.strOutputFile is not None:
        with open(tArgs.strOutputFile, "w") as f:
            f.write(strPrettyXml)


# Get chip types, boards and version from an XML file.
# Get attributes 'chip_type', 'board' and 'version' from the root element
# and split chip type and board as a comma-separated list.
def xml_get_info(strInputPath, strTag):
    logging.debug('Reading the XML file from "%s".' % strInputPath)

    tFile = open(strInputPath, 'rt')
    strXml = tFile.read()
    tFile.close()
    tXmlRoot = ElementTree.fromstring(strXml)

    if tXmlRoot.tag != strTag:
        tNode = tXmlRoot.find(strTag)
        if tNode is None:
            raise Exception("Tag '%s' not found!" % strTag)
    
    astrChipTypes = None
    astrBoards = None
    strVersion = None
    
    # Get the chiptype and version attributes.
    if 'chip_type' in tXmlRoot.attrib:
        strChiptypes = tXmlRoot.attrib['chip_type']
        astrChipTypes = strChiptypes.split(",")
    else:
        raise Exception('Missing attribute "chip_type"')
        
    if 'board' in tXmlRoot.attrib:
        strBoards = tXmlRoot.attrib['board']
        astrBoards = strBoards.split(",")
    
    return astrChipTypes, astrBoards, strVersion


# If strPath is enclosed in double quotes, remove the quotes.
def path_unquote(strPath):
    if strPath[0]=='"' and strPath[-1]=='"':
        return strPath[1:-1]
    else:
        return strPath

# if strPath contains a space, enclose it in double quotes.
def path_space_quote(strPath):
    if ' ' in strPath:
        return '"%s"' % strPath
    else:
        return strPath


# Find the GUI definition file for chip and board and get the peripheral IDs defined in it.
def get_peripherals(strChipID, strBoardID):
    astrPeripheralIDs = None 
    for tCombo in atKnownCombos:
        if tCombo['chip_id']==strChipID and tCombo['board_id']==strBoardID:
            strGuiXml = tCombo['gui']
            print('Scanning GUI file %s for peripherals' % strGuiXml)
            tPinning = Pinning()
            tPinning.read(strGuiXml)
            astrPeripheralIDs = tPinning.get_peripheral_ids()
    return astrPeripheralIDs

    
# list dynamic cfg: 
# Load each overlay and check if it is applicable to the selected chip type and board.
# If the overlay does not contain a board attribute, it is applicable to all boards.

# Extension (suggestion):
# - Use chip type and board name from the command line to get the gui XML file.
# - Extract the peripheral IDs from the gui file.
# - Filter by these peripheral IDs

def list_dynamic_cfg(tArgs):
    # We assume that this is always set.
    strLibPath = tArgs.strLibPath 
    
    # If strLibPath is not set, use the location of the HWConfig tool.
    if strLibPath == None:
        # Path to this script
        this_path = os.path.realpath(__file__)
        # Directory of this script
        strLibPath = os.path.dirname(this_path)
        
        # Expand environment variables - is this necessary?
        strLibPath = os.path.expandvars(strLibPath)
        strLibPath = os.path.abspath(strLibPath)

        strOverlayPath = os.path.join(strLibPath, 'overlay')
        
    else:
        strLibPath = path_unquote(strLibPath) 
        
        # Expand environment variables - is this necessary?
        strLibPath = os.path.expandvars(strLibPath)
        strLibPath = os.path.abspath(strLibPath)
    
        strOverlayPath = strLibPath

    # Check if the path exists and is a directory 
    if os.path.isdir(strOverlayPath) is not True:
        strErr = 'Path does not exist or is not a directory: %s' % (strOverlayPath)
        logging.error(strErr)
        raise Exception(strErr)
        
    strChipType = tArgs.strChipType
    strBoard = tArgs.strBoard
    astrDynCfg = []
    strPattern = "*.xml" # Filtering using fnmatch.filter is case-insensitive
    for strDir, astrSubdirs, astrFiles in os.walk(strOverlayPath):
        for strFile in fnmatch.filter(astrFiles, strPattern):
            strFilePath = os.path.join(strDir, strFile)
            astrChipTypes, astrBoards, strVersion = xml_get_info(strFilePath, 'peripherals')
            if strChipType in astrChipTypes and (strBoard is None or astrBoards is None or strBoard in astrBoards):
                astrDynCfg.append(strFilePath)
            
    # Print to console
    print('>>----------------------------- dynamic cfg')
    for strFile in astrDynCfg:
        print(strFile)
    print('<<----------------------------- dynamic cfg')

    # Write in XML format to file strOutputFile, if specified
    tDoc = dom.Document()
    tNodeRoot = tDoc.createElement("dynamic_cfg_list")
    tDoc.appendChild(tNodeRoot)
    
    for strFile in astrDynCfg:
        tNode = tDoc.createElement("dynamic_cfg")
        tNode.setAttribute("file", strFile)
        tNodeRoot.appendChild(tNode)
        
    strPrettyXml = tDoc.toprettyxml()
    if tArgs.strOutputFile is not None:
        with open(tArgs.strOutputFile, "w") as f:
            f.write(strPrettyXml)
        
    
def update_hwconfig(tArgs):
    fUpdated = False
    logging.info(version_string)
    
    # Read the hwconfig.
    tHwConfig = HwConfig()
    tHwConfig.read_hwconfig(tArgs.strHwConfigFile)
    
    # Get the tool_version chip_type attributes
    strToolVersion = tHwConfig.get_doc_version() # tool_version attribute of the hwconfig tag
    strChipType = tHwConfig.get_chip_type()
    strChipType = resolve_chip_type_alias(strChipType)
    strCurrentVersion = __revision__
        
    if strChipType in ['netx90_rev0', 'netx90_rev1']:
        logging.debug("update_hwconfig: netx 90 updates")
        if strToolVersion == '3.0.8':
            logging.info("Applying updates for v3.0.8.")
            tHwConfig.update_hwconfig_xm0()
            tHwConfig.update_hwconfig_board_id_default()
            tHwConfig.update_hwconfig_hwcinfo_v1()
            tHwConfig.update_hwconfig_sqi_param_v1()
            fUpdated = True
        elif strToolVersion == '3.0.11':
            logging.info("Applying updates for v3.0.11.")
            tHwConfig.update_hwconfig_board_id_default()
            tHwConfig.update_hwconfig_hwcinfo_v1()
            tHwConfig.update_hwconfig_sqi_param_v1()
            fUpdated = True
        elif strToolVersion == '3.0.15':
            logging.info("Applying updates for v3.0.15.")
            tHwConfig.update_hwconfig_board_id_nrp_h90_re()
            fUpdated = True
        elif strToolVersion == strCurrentVersion:
            logging.info("The hardware config is up to date, no update is necessary.")
        else:
            aiCurVer = parseVersionString(strCurrentVersion)
            aiHwcVer = parseVersionString(strToolVersion)
            if aiHwcVer < aiCurVer:
                raise Exception("The hardware config cannot be updated (version not supported).")
            if aiHwcVer > aiCurVer:
                raise Exception('The tool_version of the hardware config is newer than the hwconfig tool (%s > %s). You need to update the hwconfig tool.' % (strToolVersion, strCurrentVersion))

    if fUpdated==True:
        logging.info("The hardware config has been updated.")
        logging.info("Setting version to %s" % (strCurrentVersion))
        tHwConfig.set_doc_version(strCurrentVersion)
        
    if tArgs.strOutputFile is not None:
        tHwConfig.write_hwconfig(tArgs.strOutputFile)


