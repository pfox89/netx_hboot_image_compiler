# netx_hboot_image_compiler

This generates second-stage bootloader configurations for the netX90 MCU from Hilscher.

It is based on the hboot_image_compiler tool distributed by Hilscher
[here](https://github.com/muhkuh-sys/org.muhkuh.tools-hboot_image_compiler). 
It has been modified to be installable as a standalone module and to be compatible with Python 3.

# Usage

To generate a hwconfig XML patch file from a basic hwconfig XML description:
```Shell
python -m netx_boot_image_compiler.hwconfig make_hboot_xml -p netx90_rev1_peripherals.xml hardware_config.xml hardware_config.hboot.xml
```
To generate a hwconfig binary image:
```Shell
python -m netx_hboot_image_compiler -n NETX90B -A hw_config=hardware_config.hboot.xml top_hboot_image_hwc.xml hardware_config.hwc
```
