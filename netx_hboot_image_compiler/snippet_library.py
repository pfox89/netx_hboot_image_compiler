# -*- coding: utf-8 -*-

import hashlib
import os
import os.path
import sqlite3
import xml.dom.minidom


class SnippetLibrary:
    # Print debug messages.
    __fDebug = False

    # The filename for the database.
    __strDatabasePath = None

    # The database connection.
    __tDb = None

    # The list of folders to scan recursively for snippets.
    __astrSnippetSearchPaths = None

    # The snippet library was already scanned if this flag is set.
    __fSnipLibIsAlreadyScanned = None

    def __init__(self, strDatabasePath, astrSnippetSearchPaths, debug=False):
        self.__fDebug = bool(debug)

        # Set the filename of the SQLITE3 database.
        self.__strDatabasePath = strDatabasePath
        if self.__fDebug:
            print('[SnipLib] Configuration: Database path = "%s"' % strDatabasePath)

        # The connection to the database is not open yet.
        self.__tDb = None

        # Convert all search paths to absolute paths.
        self.__astrSnippetSearchPaths = []
        for strPath in astrSnippetSearchPaths:
            self.__astrSnippetSearchPaths.append(os.path.abspath(strPath))

        # Print all search paths in debug mode.
        if self.__fDebug:
            for strPath in self.__astrSnippetSearchPaths:
                print('[SnipLib] Configuration: Search path "%s"' % strPath)

        # The snippet library was not scanned yet.
        self.__fSnipLibIsAlreadyScanned = False

    def __xml_get_all_text(self, tNode):
        astrText = []
        for tChild in tNode.childNodes:
            if (tChild.nodeType == tChild.TEXT_NODE) or (tChild.nodeType == tChild.CDATA_SECTION_NODE):
                astrText.append(str(tChild.data))
        return ''.join(astrText)

    def __xml_get_node(self, tBaseNode, strTagName):
        tNode = None
        for tChildNode in tBaseNode.childNodes:
            if tChildNode.nodeType == tChildNode.ELEMENT_NODE:
                if tChildNode.localName == strTagName:
                    tNode = tChildNode
                    break

        return tNode

    def __get_snip_hash(self, strAbsPath):
        # Get the SHA384 hash.
        tFile = open(strAbsPath, 'rb')
        tHash = hashlib.sha384()
        fEof = False
        while fEof is False:
            strData = tFile.read(2048)
            tHash.update(strData)
            if len(strData) < 2048:
                fEof = True
        strDigest = tHash.hexdigest()
        tFile.close()

        # Return the hash.
        return strDigest

    def __db_open(self):
        tDb = self.__tDb
        if tDb is None:
            tDb = sqlite3.connect(self.__strDatabasePath)
            self.__tDb = tDb

        tCursor = tDb.cursor()

        # Construct the "CREATE" statement for the "snippets" table.
        strCreateStatement = 'CREATE TABLE snippets (id INTEGER PRIMARY KEY, search_path TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL, groupid TEXT NOT NULL, artifact TEXT NOT NULL, version TEXT NOT NULL, clean INTEGER DEFAULT 0)'
        if self.__fDebug:
            print('[SnipLib] Database: The current CREATE statement for the "snippet" table is "%s".' % strCreateStatement)

        # Compare the current "CREATE" statement with the statement of the
        # existing table.
        tCursor.execute('SELECT sql FROM sqlite_master WHERE name="snippets"')
        tRes = tCursor.fetchone()
        if tRes is None:
            # The table does not exist yet. Create it now.
            if self.__fDebug:
                print('[SnipLib] Database: The "snippet" table does not yet exist. Create it now.')
            tCursor.execute(strCreateStatement)
            tDb.commit()
        elif tRes[0] != strCreateStatement:
            if self.__fDebug:
                print('[SnipLib] Database: The existing "snippet" table has a different CREATE statement: "%s".' % tRes[0])
                print('[SnipLib] Database: Delete the existing table and re-create it.')
            # Delete the old table.
            tCursor.execute('DROP TABLE snippets')
            tDb.commit()
            # Create a new table.
            tCursor.execute(strCreateStatement)
            tDb.commit()
        else:
            if self.__fDebug:
                print('[SnipLib] Database: The existing "snippet" table was created with the correct statement.')

    def __snippet_get_gav(self, strPath):
        strGroup = None
        strArtifact = None
        strVersion = None

        # Parse the snippet.
        try:
            tXml = xml.dom.minidom.parse(strPath)
        except xml.dom.DOMException as tException:
            # Invalid XML, ignore.
            strArtifact = 'No valid XML: %s' % repr(tException)
            tXml = None

        if tXml is not None:
            # Search for the "Info" node.
            tInfoNode = self.__xml_get_node(tXml.documentElement, 'Info')
            if tInfoNode is None:
                # No Info node -> ignore the file.
                strArtifact = 'It has no "Info" node.'
            else:
                # Get the "group", "artifact" and "version" attributes.
                strGroup = tInfoNode.getAttribute('group')
                strArtifact = tInfoNode.getAttribute('artifact')
                strVersion = tInfoNode.getAttribute('version')
                if len(strGroup) == 0:
                    strGroup = None
                    strArtifact = 'The "group" attribute of an "Info" node must not be empty.'
                elif len(strArtifact) == 0:
                    strGroup = None
                    strArtifact = 'The "artifact" attribute of an "Info" node must not be empty.'
                elif len(strVersion) == 0:
                    strGroup = None
                    strArtifact = 'The "version" attribute of an "Info" node must not be empty.'

        # Return the group, artifact and version.
        return strGroup, strArtifact, strVersion

    def __sniplib_invalidate(self, strSearchPath):
        tCursor = self.__tDb.cursor()

        # Show all files which are invalidated.
        if self.__fDebug:
            print('[SnipLib] Scan: Invalidating all cached entries for the search path "%s".' % strSearchPath)
            tCursor.execute('SELECT path,groupid,artifact,version FROM snippets WHERE search_path=?', (strSearchPath, ))
            atRes = tCursor.fetchall()
            if atRes is None or len(atRes) == 0:
                print('[SnipLib] Scan:  -> No cached entries found for the search path "%s".' % strSearchPath)
            else:
                for tRes in atRes:
                    print('[SnipLib] Scan:  -> Invalidating entry G="%s" A="%s" V="%s" at "%s".' % (tRes[1], tRes[2], tRes[3], tRes[0]))

        # Mark all files to be deleted. This flag will be cleared for all files which are present.
        tCursor.execute('UPDATE snippets SET clean=1 WHERE search_path=?', (strSearchPath, ))
        self.__tDb.commit()

    def __sniplib_scan(self, strSearchPath):
        if self.__fDebug:
            print('[SnipLib] Scan: Scanning search path "%s".' % strSearchPath)

        tCursor = self.__tDb.cursor()
        # Search all files recursively.
        for strRoot, astrDirs, astrFiles in os.walk(strSearchPath, followlinks=True):
            # Process all files in this folder.
            for strFile in astrFiles:
                # Get the extension of the file.
                strDummy, strExt = os.path.splitext(strFile)
                if strExt == '.xml':
                    # Get the absolute path for the file.
                    strAbsPath = os.path.join(strRoot, strFile)

                    # Get the stamp of the snip.
                    strDigest = self.__get_snip_hash(strAbsPath)

                    if self.__fDebug:
                        print('[SnipLib] Scan:  -> Found snippet at "%s" with the hash "%s".' % (strAbsPath, strDigest))

                    # Search the snippet in the database.
                    tCursor.execute('SELECT id,hash FROM snippets WHERE search_path=? AND path=?', (strSearchPath, strAbsPath))
                    atResults = tCursor.fetchone()
                    if atResults is None:
                        # The snippet is not present in the database yet.
                        if self.__fDebug:
                            print('[SnipLib] Scan:      -> The snippet is not registered in the cache yet. Make a new entry now.')
                        strGroup, strArtifact, strVersion = self.__snippet_get_gav(strAbsPath)
                        if strGroup is None:
                            if self.__fDebug:
                                print('[SnipLib] Scan:      -> Warning: Ignoring file "%s". %s' % (strAbsPath, strArtifact))

                        # Make a new entry.
                        tCursor.execute('INSERT INTO snippets (search_path, path, hash, groupid, artifact, version) VALUES (?, ?, ?, ?, ?, ?)', (strSearchPath, strAbsPath, strDigest, strGroup, strArtifact, strVersion))

                    else:
                        # Compare the hash of the file.
                        if atResults[1] == strDigest:
                            # The hash is the same -> the file is already known.
                            if self.__fDebug:
                                print('[SnipLib] Scan:      -> The snippet is already registered in the cache.')

                            # Found the file. Do not delete it from the database.
                            tCursor.execute('UPDATE snippets SET clean=0 WHERE id=?', (atResults[0], ))

                        else:
                            # The hash differs. Update the entry with the new hash, group, artifact and version.
                            if self.__fDebug:
                                print('[SnipLib] Scan:      -> The snippet has a different hash than the entry in the cache. Update the metadata now.')

                            strGroup, strArtifact, strVersion = self.__snippet_get_gav(strAbsPath)
                            if strGroup is None:
                                if self.__fDebug:
                                    print('[SnipLib] Scan:      -> Warning: Ignoring file "%s". %s' % (strAbsPath, strArtifact))
                            else:
                                tCursor.execute('UPDATE snippets SET hash=?, groupid=?, artifact=?, version=?, clean=0 WHERE id=?', (strDigest, strGroup, strArtifact, strVersion, atResults[0]))

    def __sniplib_forget_invalid_entries(self, strSearchPath):
        # Remove all entries from the cache which are marked for clean.
        tCursor = self.__tDb.cursor()

        # Show all files which are removed from the cache.
        if self.__fDebug:
            print('[SnipLib] Scan: Remove all invalidated entries from the cache for the search path "%s".' % strSearchPath)
            tCursor.execute('SELECT path,groupid,artifact,version FROM snippets WHERE clean!=0 AND search_path=?', (strSearchPath, ))
            atRes = tCursor.fetchall()
            if atRes is None or len(atRes) == 0:
                print('[SnipLib] Scan:  -> No cache entries are removed.')
            else:
                for tRes in atRes:
                    print('[SnipLib] Scan:  -> Removing cache entry G="%s" A="%s" V="%s" at "%s".' % (tRes[1], tRes[2], tRes[3], tRes[0]))

        tCursor.execute('DELETE FROM snippets WHERE clean!=0 AND search_path=?', (strSearchPath, ))
        self.__tDb.commit()

    def find(self, strGroup, strArtifact, strVersion, atParameter):
        # Open the connection to the database.
        self.__db_open()

        # Scan each search path.
        if self.__fSnipLibIsAlreadyScanned is not True:
            for strSearchPath in self.__astrSnippetSearchPaths:
                self.__sniplib_invalidate(strSearchPath)
                self.__sniplib_scan(strSearchPath)
                self.__sniplib_forget_invalid_entries(strSearchPath)
            self.__fSnipLibIsAlreadyScanned = True

        # Search for the snippet in each search path. Stop on the first hit.
        atMatch = None
        tCursor = self.__tDb.cursor()
        for strSearchPath in self.__astrSnippetSearchPaths:
            tCursor.execute('SELECT path FROM snippets WHERE search_path=? AND groupid=? AND artifact=? AND version=?', (strSearchPath, strGroup, strArtifact, strVersion))
            atResult = tCursor.fetchone()
            if atResult is not None:
                atMatch = atResult
                break

        # Get the snippet name for messages.
        strSnippetName = 'G="%s", A="%s", V="%s"' % (strGroup, strArtifact, strVersion)

        if atMatch is None:
            # No matching snippet found.
            raise Exception('No matching snippet found for %s.' % strSnippetName)

        strAbsPath = atMatch[0]
        if self.__fDebug:
            print('[SnipLib] Resolve: Found %s at "%s".' % (strSnippetName, strAbsPath))

        # Try to parse the snippet file.
        try:
            tXml = xml.dom.minidom.parse(strAbsPath)
        except xml.dom.DOMException as tException:
            # Invalid XML, ignore.
            raise Exception('Failed to parse the snippet %s: %s' % (strSnippetName, repr(tException)))

        tRootNode = tXml.documentElement

        # Find all parameters.
        # The "ParameterList" node is optional.
        atParameterList = {}
        tParameterListNode = self.__xml_get_node(tRootNode, 'ParameterList')
        if tParameterListNode is not None:
            # Loop over all child nodes.
            for tChildNode in tParameterListNode.childNodes:
                if tChildNode.nodeType == tChildNode.ELEMENT_NODE:
                    if tChildNode.localName == 'Parameter':
                        # Get the "name" atribute.
                        strName = tChildNode.getAttribute('name')
                        if len(strName) == 0:
                            raise Exception('Failed to parse the snippet %s: a parameter node is missing the "name" attribute!' % strSnippetName)
                        # Get the "default" attribute. It is optional.
                        tDefault = None
                        if tChildNode.hasAttribute('default'):
                            tDefault = tChildNode.getAttribute('default')
                        # Is the parameter already present?
                        if strName in atParameterList:
                            raise Exception('Failed to parse the snippet %s: the parameter is requested more than once in the snippet definition!' % strSnippetName)
                        else:
                            atParameterList[strName] = tDefault
                    else:
                        raise Exception('Failed to parse the snippet %s: unexpected tag "%s".' % (strSnippetName, tChildNode.localName))

        # Combine the parameters.
        atReplace = {}
        astrMissing = []
        # Add all default values and find missing values.
        for strName, tDefault in iter(list(atParameterList.items())):
            if tDefault is not None:
                atReplace[strName] = tDefault
            if strName not in atParameter:
                astrMissing.append(strName)
        if len(astrMissing) != 0:
            raise Exception('Failed to instanciate snippet %s: missing parameter %s' % (strSnippetName, ', '.join(astrMissing)))

        # Add all required parameters which have assigned values.
        # Find unused parameter.
        astrUnused = []
        for strName, strValue in iter(list(atParameter.items())):
            if strName in atParameterList:
                atReplace[strName] = strValue
            else:
                astrUnused.append(strName)

        if len(astrUnused) != 0:
            if self.__fDebug:
                print('[SnipLib] Resolve: the snippet %s does not use the following parameters: %s' % (strSnippetName, ', '.join(astrUnused)))

        # Find the "Snippet" node.
        tSnippetNode = self.__xml_get_node(tRootNode, 'Snippet')
        if tSnippetNode is None:
            raise Exception('The snippet definition "%s" has no "Snippet" node.' % strAbsPath)

        # Get the text contents.
        strSnippet = self.__xml_get_all_text(tSnippetNode)

        return (strSnippet, atReplace, strAbsPath)
