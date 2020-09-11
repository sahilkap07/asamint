#!/usr/bin/env python
# -*- coding: utf-8 -*-

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020 by Christoph Schueler <cpu12.gems.googlemail.com>

   All Rights Reserved

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License along
   with this program; if not, write to the Free Software Foundation, Inc.,
   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

   s. FLOSS-EXCEPTION.txt
"""
__author__ = 'Christoph Schueler'

import logging

from asamint.utils import create_elem
from asamint.config import Configuration

import asammdf
from asammdf import MDF, Signal

from pya2l import DB
import pya2l.model as model
from pya2l.api.inspect import Measurement, ModPar

from lxml.etree import (Comment, Element, ElementTree, DTD, SubElement, XMLSchema, parse, tostring)

"""
Channel name (cn)           Acquisition name (gn)   Source name (cs,gs)

MCD-2 MC CHARACTERISTIC /   SOURCE / EVENT name     PROJECT name
MEASUREMENT /
AXIS_PTS name

"""

class MDFCreator:
    """
    """

    PROJECT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "LOGLEVEL":                 (str,    False,  "WARN"),
        "MDF_VERSION":              (str,    False,   "4.10"),
        "AUTHOR":                   (str,    False,  ""),
        "DEPARTMENT":               (str,    False,  ""),
        "PROJECT":                  (str,    False,  ""),
        "SUBJECT":                  (str,    False,  ""),
    }

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "DESCRIPTION":              (str,    False,  ""),
        "TIME_SOURCE":              (str,    False,  "local PC reference timer"),
    }

    def __init__(self, session_obj, mdf_obj, mdf_filename = None, project_config = None, experiment_config = None):
        self._session_obj = session_obj
        self._mdf_obj = mdf_obj
        self._mdf_filename = mdf_filename

        self.project_config = Configuration(MDFCreator.PROJECT_PARAMETER_MAP or {}, project_config or {})
        self.experiment_config = Configuration(MDFCreator.EXPERIMENT_PARAMETER_MAP or {}, project_config or {})
        self.logger = logging.getLogger("MDFCreator")
        self.logger.setLevel(self.project_config.get("LOGLEVEL"))

        self._mod_par = ModPar(self._session_obj)
        systemConstants = self._mod_par.systemConstants

        hd_comment = self.hd_comment(systemConstants)
        print(hd_comment)

    def hd_comment(self, sys_constants = None, units = None):
        """
        Parameters
        ----------
        """
        mdf_ver_major = int(self._mdf_obj.version.split(".")[0])
        if mdf_ver_major < 4:
            pass
        else:
            elem_root = Element("HDcomment")
            create_elem(elem_root, "TX", self.experiment_config.get("DESCRIPTION"))
            if time_source:
                create_elem(elem_root, "time_source", self.experiment_config.get("TIME_SOURCE"))
            if sys_constants:
                elem_constants = create_elem(elem_root, "constants")
                for name, value in sys_constants.items():
                    create_elem(elem_constants, "const", text = str(value), attrib = {"name": name})
            cps = create_elem(elem_root, "common_properties")
            create_elem(cps, "e", attrib = {"name": "author"}, text = self.project_config.get("AUTHOR"))
            create_elem(cps, "e", attrib = {"name": "department"}, text = self.project_config.get("DEPARTMENT"))
            create_elem(cps, "e", attrib = {"name": "project"}, text = self.project_config.get("PROJECT"))
            create_elem(cps, "e", attrib = {"name": "subject"}, text = self.project_config.get("SUBJECT"))
            return tostring(elem_root, encoding = "UTF-8", pretty_print = True)


def create_mdf(session_obj, mdf_obj, mdf_filename = None):
    """
    Parameters
    ----------
    """

    signals = []
    measurements = session_obj.query(model.Measurement).order_by(model.Measurement.name).all()
    for measurement in measurements:
        #print("\tMEAS", measurement)
        cm_name = measurement.conversion
        comment = measurement.longIdentifier
        unit = None
        data_type = measurement.datatype # Don't know how to set data types on Signals...
        conversion = None
        if cm_name == "NO_COMPU_METHOD":
            conversion = None
        else:
            cm = session_obj.query(model.CompuMethod).filter(model.CompuMethod.name ==  cm_name).first()
            cm_type = cm.conversionType
            unit = cm.unit
            if cm_type == "IDENTICAL":
                conversion = None
            elif cm_type == "FORM":
                formula_inv = cm.formula.formula_inv.g_x if cm.formula.formula_inv else None
                conversion = {
                    "formula": cm.formula.f_x
                }
            elif cm_type == "LINEAR":
                conversion = {
                    "a": cm.coeffs_linear.a,
                    "b": cm.coeffs_linear.b,
                }
            elif cm_type == "RAT_FUNC":
                conversion = {
                    "P1": cm.coeffs.a,
                    "P2": cm.coeffs.b,
                    "P3": cm.coeffs.c,
                    "P4": cm.coeffs.d,
                    "P5": cm.coeffs.e,
                    "P6": cm.coeffs.f,
                }
            elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
                interpolation = True if cm_type == "TAB_INTP" else False
                cvt = session_obj.query(model.CompuTab).filter(model.CompuTab.name == cm.compu_tab_ref.conversionTable).first()
                pairs = cvt.pairs
                num_values = len(pairs)
                default_value = cvt.default_value_numeric.display_value if cvt.default_value_numeric else None
                print("\tTAB_INTP", measurement.name, cvt.pairs, default_value)
                in_values = [x.inVal for x in pairs]
                out_values = [x.outVal for x in pairs]
                conversion = {"raw_{}".format(i): in_values[i] for i in range(num_values)}
                conversion.update({"phys_{}".format(i): out_values[i] for i in range(num_values)})
                conversion.update(default = default_value)
                conversion.update(interpolation = interpolation)
            elif cm_type == "TAB_VERB":
                cvt = session_obj.query(model.CompuVtab).filter(model.CompuVtab.name == cm.compu_tab_ref.conversionTable).first()
                if cvt:
                    pairs = cvt.pairs
                    num_values = len(pairs)
                    in_values = [x.inVal for x in pairs]
                    out_values = [x.outVal for x in pairs]
                    conversion = {"val_{}".format(i): in_values[i] for i in range(num_values)}
                    conversion.update({"text_{}".format(i): out_values[i] for i in range(num_values)})
                    conversion.update(default = cvt.default_value.display_string if cvt.default_value else None)
                else:
                    cvt = session_obj.query(model.CompuVtabRange).filter(model.CompuVtabRange.name == \
                            cm.compu_tab_ref.conversionTable).first()
                    if cvt:
                        triples = cvt.triples
                        num_values = len(triples)
                        lower_values = [x.inValMin for x in triples]
                        upper_values = [x.inValMax for x in triples]
                        text_values = [x.outVal for x in triples]
                        conversion = {"lower_{}".format(i): lower_values[i] for i in range(num_values)}
                        conversion.update({"upper_{}".format(i): upper_values[i] for i in range(num_values)})
                        conversion.update({"text_{}".format(i): text_values[i] for i in range(num_values)})
                        conversion.update(default = bytes(cvt.default_value.display_string, encoding = "utf-8") \
                                if cvt.default_value else b'')
                    else:
                        conversion = None
        #print(measurement.name, conversion)
        signal = Signal(samples = [0, 0, 0, 0], timestamps = [0, 0, 0, 0], name = measurement.name, unit = unit, conversion = conversion, comment = comment)
        signals.append(signal)
    mdf_obj.append(signals)
    mdf_obj.save(dst = mdf_filename, overwrite = True)
