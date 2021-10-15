import logging

atLogLevels = {
    'critical': logging.CRITICAL,
    'error': logging.ERROR,
    'warning': logging.WARNING,
    'info': logging.INFO,
    'debug': logging.DEBUG
}

# Import version info.
# This is the version of the HWConfig tool.
version_major = 3
version_minor = 1
version_micro = 0
version_clean = True
version_commit_count = 0
version_commit_hash = 'adc62f148777'

# Build the string reported by the --version option.
# The version is based on the last tag.
# If we are not on a tag without further commits, append the hash of the
# current head and the number of commits.
__revision__ = '{}.{}.{}'.format(version_major, version_minor, version_micro)
version_string = 'hwconfig v{} by cthelen@hilscher.com, modified by paul.fox@mts.com'.format(__revision__)
if version_clean!=True:
    version_string = version_string + ', DEVELOPMENT: Git {}, {} commits after tag'.format(version_commit_hash, version_commit_count)

if version_clean==True:
    hwconfig_tool_version_short = __revision__
else:
    hwconfig_tool_version_short = __revision__ + '.' + version_commit_hash
