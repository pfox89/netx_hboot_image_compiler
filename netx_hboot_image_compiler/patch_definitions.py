# -*- coding: utf-8 -*-

import ast
import xml.dom.minidom

# ----------------------------------------------------------------------------
#
# This class replaces literal values in AST expressions with a dictionary.
#


class RewriteName(ast.NodeTransformer):
    __atConstants = None
    __atTemporaryConstants = None

    def setConstants(self, atConstants):
        self.__atConstants = atConstants

    def setTemporaryConstants(self, atConstants):
        self.__atTemporaryConstants = atConstants

    def visit_Name(self, node):
        tNode = None
        if node.id in self.__atConstants:
            tValue = self.__atConstants[node.id]
            tNode = ast.copy_location(ast.Num(n=tValue), node)
        elif (self.__atTemporaryConstants is not None) and (node.id in self.__atTemporaryConstants):
            tValue = self.__atTemporaryConstants[node.id]
            tNode = ast.copy_location(ast.Num(n=tValue), node)
        else:
            raise Exception('Unknown constant %s.' % node.id)
        return tNode

# ----------------------------------------------------------------------------


class PatchDefinitions:
    # This is a dictionary with all the data from the patch definition.
    m_atPatchDefinitions = None

    # This is a dictionary of all constants. They are read from the patch
    # definition.
    m_atConstants = None

    m_cAstConstResolver = None

    def __init__(self):
        self.m_atPatchDefinitions = dict({})
        self.m_atConstants = dict({})
        self.m_cAstConstResolver = RewriteName()
        self.m_cAstConstResolver.setConstants(self.m_atConstants)

    def read_patch_definition(self, tInput):
        # A string must be the filename of the XML.
        if isinstance(tInput, ("".__class__, "".__class__)):
            tXml = xml.dom.minidom.parse(tInput)
        elif isinstance(tInput, xml.dom.minidom.Document):
            tXml = tInput
        else:
            raise Exception('Unknown input document: %s' % repr(tInput))

        # Loop over all children.
        for tOptionsNode in tXml.documentElement.childNodes:
            # Is this a node element with the name 'Options'?
            if (tOptionsNode.nodeType == tOptionsNode.ELEMENT_NODE) and (tOptionsNode.localName == 'Options'):
                # Loop over all children.
                for tOptionNode in tOptionsNode.childNodes:
                    # Is this a node element with the name 'Options'?
                    if (tOptionNode.nodeType == tOptionNode.ELEMENT_NODE) and (tOptionNode.localName == 'Option'):
                        # Get the ID.
                        strOptionId = tOptionNode.getAttribute('id')
                        if strOptionId == '':
                            raise Exception('Missing id attribute!')
                        if strOptionId in self.m_atPatchDefinitions:
                            raise Exception('ID %s double defined!' % strOptionId)

                        strOptionValue = tOptionNode.getAttribute('value')
                        if strOptionValue == '':
                            raise Exception('Missing value attribute!')
                        ulOptionValue = int(strOptionValue, 0)

                        # Loop over all children.
                        atElements = []
                        for tElementNode in tOptionNode.childNodes:
                            # Is this a node element with the name 'Element'?
                            if (tElementNode.nodeType == tElementNode.ELEMENT_NODE) and (tElementNode.localName == 'Element'):
                                # Get the ID.
                                strElementId = tElementNode.getAttribute('id')
                                if strElementId == '':
                                    raise Exception('Missing id attribute!')

                                # Get the size attribute.
                                strSize = tElementNode.getAttribute('size')
                                if strSize == '':
                                    raise Exception('Missing size attribute!')
                                ulSize = int(strSize, 0)

                                # Get the type attribute.
                                strType = tElementNode.getAttribute('type')
                                if strType == '':
                                    raise Exception('Missing type attribute!')
                                ulType = int(strType, 0)

                                atElements.append((strElementId, ulSize, ulType))
                        atDesc = dict({})
                        atDesc['value'] = ulOptionValue
                        atDesc['elements'] = atElements
                        self.m_atPatchDefinitions[strOptionId] = atDesc

            elif (tOptionsNode.nodeType == tOptionsNode.ELEMENT_NODE) and (tOptionsNode.localName == 'Definitions'):
                # Loop over all children.
                for tDefinitionNode in tOptionsNode.childNodes:
                    if (tDefinitionNode.nodeType == tDefinitionNode.ELEMENT_NODE) and (tDefinitionNode.localName == 'Definition'):
                        # Get the name.
                        strDefinitionName = tDefinitionNode.getAttribute('name')
                        if strDefinitionName == '':
                            raise Exception('Missing name attribute!')
                        if strDefinitionName in self.m_atConstants:
                            raise Exception('Name "%s" double defined!' % strDefinitionName)

                        strDefinitionValue = tDefinitionNode.getAttribute('value')
                        if strDefinitionValue == '':
                            raise Exception('Missing value attribute!')
                        ulDefinitionValue = int(strDefinitionValue, 0)

                        self.m_atConstants[strDefinitionName] = ulDefinitionValue

    def resolve_constants(self, tAstNode):
        return self.m_cAstConstResolver.visit(tAstNode)

    def get_patch_definition(self, strOptionId):
        if strOptionId not in self.m_atPatchDefinitions:
            raise Exception('The option ID %s was not found!' % strOptionId)

        return self.m_atPatchDefinitions[strOptionId]

    def setTemporaryConstants(self, atConstants):
        self.m_cAstConstResolver.setTemporaryConstants(atConstants)
