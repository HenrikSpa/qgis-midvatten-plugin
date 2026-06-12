"""
/***************************************************************************
 This part of the Midvatten plugin tests the module that handles importing of
  measurements.

 This part is to a big extent based on QSpatialite plugin.
                             -------------------
        begin                : 2016-03-08
        copyright            : (C) 2016 by joskal (HenrikSpa)
        email                : groundwatergis [at] gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from unittest import mock
from unittest.mock import call
import pytest

from midvatten.test import utils_for_tests
from midvatten.test import mocks_for_tests
from midvatten.tools.import_interlab4 import Interlab4Import
from midvatten.tools.obsid_assignment_dialog import DialogOutcome
from midvatten.tools.utils import db_utils, file_utils


@pytest.mark.spatialite
class TestInterlab4Importer(utils_for_tests.MidvattenTestSpatialiteNotCreated):
    def setup_method(self):
        super().setup_method()
        self.importinstance = Interlab4Import(self.iface, self.midvatten.ms)

    def test_interlab4_parse_filesettings_utf16(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-16",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsn",
        )
        with file_utils.tempinput("\n".join(interlab4_lines), "utf-16") as testfile:
            result_string = str(
                utils_for_tests.dict_to_sorted_list(
                    self.importinstance.parse_filesettings(testfile)
                )
            )

        reference_string = "['False', '4.0', 'utf-16', ',', 'False']"
        print(result_string)
        print(reference_string)
        assert result_string == reference_string

    def test_interlab4_parse_filesettings_utf8(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsn",
        )
        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            result_string = str(
                utils_for_tests.dict_to_sorted_list(
                    self.importinstance.parse_filesettings(testfile)
                )
            )

        reference_string = "['False', '4.0', 'utf-8', ',', 'False']"
        print(result_string)
        print(reference_string)

        assert result_string == reference_string

    def test_parse_interlab4_utf16(self):

        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-16",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;;5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;ISO 17294-2;Järn;;0,06;;mg/l;;;;;;;",
            "DM-990908-2773;Saknas;Temperatur vid provtagning;;14,5;;grader C;;;;;;;",
            "DM-990908-2773;SLV METOD1990-01-01 TA;Temperatur vid ankomst;;16,8;;grader C;;;;;;Ej kylt;",
            "DM-990908-2773;ISO 17294-2;Mangan;;0,001;<;mg/l;;;;;;;",
            "#Provadm ",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2774;MFR;;;;;;Demo-Laboratoriet;NSG;DV;VV1784;Demo2 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;11:30;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2774;SS-EN ISO 7887-1/4;Färgtal;;6,5;;mg/l Pt;;;;;;;",
            "DM-990908-2774;ISO 17294-2;Järn;;0,05;<;mg/l;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid provtagning;;14,8;;grader C;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid ankomst;;17,3;;grader C;;;;;;Ej kylt;",
            "DM-990908-2774;ISO 17294-2;Mangan;;0,004;;mg/l;;;;;;; ",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-16") as testfile:
            result = self.importinstance.parse([testfile])
        result_string = ";".join(
            utils_for_tests.dict_to_sorted_list(self.importinstance.parse([testfile]))
        )
        reference_string = "DM-990908-2773;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2773;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.06;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.001;mätvärdetalanm;<;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2773;metodbeteckning;SLV METOD1990-01-01 TA;mätvärdetal;16.8;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2773;metodbeteckning;Saknas;mätvärdetal;14.5;parameter;Temperatur vid provtagning;metadata;adress;PG Vejdes väg 15;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;kommunkod;0780;lablittera;DM-990908-2773;laboratorium;Demo-Laboratoriet;namn;MFR;ort;Växjö;postnr;351 96;projekt;Demoproj;provplatsid;Demo1 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;10:15;provtyp;Utgående;provtypspecifikation;Nej;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010;DM-990908-2774;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2774;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;6.5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.05;mätvärdetalanm;<;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.004;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;17.3;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;14.8;parameter;Temperatur vid provtagning;metadata;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;lablittera;DM-990908-2774;laboratorium;Demo-Laboratoriet;namn;MFR;provplatsid;Demo2 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;11:30;provtyp;Utgående;provtypspecifikation;Nej;registertyp;VV1784;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010"

        assert result_string == reference_string

    def test_parse_interlab4_iso_8859_1(self):

        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=ISO-8859-1",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;;5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;ISO 17294-2;Järn;;0,06;;mg/l;;;;;;;",
            "DM-990908-2773;Saknas;Temperatur vid provtagning;;14,5;;grader C;;;;;;;",
            "DM-990908-2773;SLV METOD1990-01-01 TA;Temperatur vid ankomst;;16,8;;grader C;;;;;;Ej kylt;",
            "DM-990908-2773;ISO 17294-2;Mangan;;0,001;<;mg/l;;;;;;;",
            "#Provadm ",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2774;MFR;;;;;;Demo-Laboratoriet;NSG;DV;VV1784;Demo2 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;11:30;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2774;SS-EN ISO 7887-1/4;Färgtal;;6,5;;mg/l Pt;;;;;;;",
            "DM-990908-2774;ISO 17294-2;Järn;;0,05;<;mg/l;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid provtagning;;14,8;;grader C;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid ankomst;;17,3;;grader C;;;;;;Ej kylt;",
            "DM-990908-2774;ISO 17294-2;Mangan;;0,004;;mg/l;;;;;;; ",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "iso-8859-1") as testfile:
            result = self.importinstance.parse([testfile])
        result_string = ";".join(
            utils_for_tests.dict_to_sorted_list(self.importinstance.parse([testfile]))
        )
        reference_string = "DM-990908-2773;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2773;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.06;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.001;mätvärdetalanm;<;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2773;metodbeteckning;SLV METOD1990-01-01 TA;mätvärdetal;16.8;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2773;metodbeteckning;Saknas;mätvärdetal;14.5;parameter;Temperatur vid provtagning;metadata;adress;PG Vejdes väg 15;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;kommunkod;0780;lablittera;DM-990908-2773;laboratorium;Demo-Laboratoriet;namn;MFR;ort;Växjö;postnr;351 96;projekt;Demoproj;provplatsid;Demo1 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;10:15;provtyp;Utgående;provtypspecifikation;Nej;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010;DM-990908-2774;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2774;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;6.5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.05;mätvärdetalanm;<;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.004;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;17.3;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;14.8;parameter;Temperatur vid provtagning;metadata;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;lablittera;DM-990908-2774;laboratorium;Demo-Laboratoriet;namn;MFR;provplatsid;Demo2 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;11:30;provtyp;Utgående;provtypspecifikation;Nej;registertyp;VV1784;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010"

        assert result_string == reference_string

    def test_parse_interlab4_utf8(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;;5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;ISO 17294-2;Järn;;0,06;;mg/l;;;;;;;",
            "DM-990908-2773;Saknas;Temperatur vid provtagning;;14,5;;grader C;;;;;;;",
            "DM-990908-2773;SLV METOD1990-01-01 TA;Temperatur vid ankomst;;16,8;;grader C;;;;;;Ej kylt;",
            "DM-990908-2773;ISO 17294-2;Mangan;;0,001;<;mg/l;;;;;;;",
            "#Provadm ",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2774;MFR;;;;;;Demo-Laboratoriet;NSG;DV;VV1784;Demo2 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;11:30;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2774;SS-EN ISO 7887-1/4;Färgtal;;6,5;;mg/l Pt;;;;;;;",
            "DM-990908-2774;ISO 17294-2;Järn;;0,05;<;mg/l;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid provtagning;;14,8;;grader C;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid ankomst;;17,3;;grader C;;;;;;Ej kylt;",
            "DM-990908-2774;ISO 17294-2;Mangan;;0,004;;mg/l;;;;;;; ",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            result = self.importinstance.parse([testfile])
        result_string = ";".join(
            utils_for_tests.dict_to_sorted_list(self.importinstance.parse([testfile]))
        )
        reference_string = "DM-990908-2773;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2773;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.06;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.001;mätvärdetalanm;<;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2773;metodbeteckning;SLV METOD1990-01-01 TA;mätvärdetal;16.8;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2773;metodbeteckning;Saknas;mätvärdetal;14.5;parameter;Temperatur vid provtagning;metadata;adress;PG Vejdes väg 15;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;kommunkod;0780;lablittera;DM-990908-2773;laboratorium;Demo-Laboratoriet;namn;MFR;ort;Växjö;postnr;351 96;projekt;Demoproj;provplatsid;Demo1 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;10:15;provtyp;Utgående;provtypspecifikation;Nej;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010;DM-990908-2774;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2774;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;6.5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.05;mätvärdetalanm;<;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.004;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;17.3;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;14.8;parameter;Temperatur vid provtagning;metadata;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;lablittera;DM-990908-2774;laboratorium;Demo-Laboratoriet;namn;MFR;provplatsid;Demo2 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;11:30;provtyp;Utgående;provtypspecifikation;Nej;registertyp;VV1784;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010"

        assert result_string == reference_string

    def test_parse_interlab4_ignore_bland_line(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;;5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;ISO 17294-2;Järn;;0,06;;mg/l;;;;;;;",
            "DM-990908-2773;Saknas;Temperatur vid provtagning;;14,5;;grader C;;;;;;;",
            "DM-990908-2773;SLV METOD1990-01-01 TA;Temperatur vid ankomst;;16,8;;grader C;;;;;;Ej kylt;",
            "DM-990908-2773;ISO 17294-2;Mangan;;0,001;<;mg/l;;;;;;;",
            "#Provadm ",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
            "DM-990908-2774;MFR;;;;;;Demo-Laboratoriet;NSG;DV;VV1784;Demo2 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;11:30;2010-09-07;14:15;",
            "#Provdat",
            "",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2774;SS-EN ISO 7887-1/4;Färgtal;;6,5;;mg/l Pt;;;;;;;",
            "DM-990908-2774;ISO 17294-2;Järn;;0,05;<;mg/l;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid provtagning;;14,8;;grader C;;;;;;;",
            "DM-990908-2774;Saknas;Temperatur vid ankomst;;17,3;;grader C;;;;;;Ej kylt;",
            "DM-990908-2774;ISO 17294-2;Mangan;;0,004;;mg/l;;;;;;; ",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            result = self.importinstance.parse([testfile])
        result_string = ";".join(
            utils_for_tests.dict_to_sorted_list(self.importinstance.parse([testfile]))
        )
        reference_string = "DM-990908-2773;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2773;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.06;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2773;metodbeteckning;ISO 17294-2;mätvärdetal;0.001;mätvärdetalanm;<;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2773;metodbeteckning;SLV METOD1990-01-01 TA;mätvärdetal;16.8;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2773;metodbeteckning;Saknas;mätvärdetal;14.5;parameter;Temperatur vid provtagning;metadata;adress;PG Vejdes väg 15;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;kommunkod;0780;lablittera;DM-990908-2773;laboratorium;Demo-Laboratoriet;namn;MFR;ort;Växjö;postnr;351 96;projekt;Demoproj;provplatsid;Demo1 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;10:15;provtyp;Utgående;provtypspecifikation;Nej;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010;DM-990908-2774;Färgtal;enhet;mg/l Pt;lablittera;DM-990908-2774;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;6.5;parameter;Färgtal;Järn;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.05;mätvärdetalanm;<;parameter;Järn;Mangan;enhet;mg/l;lablittera;DM-990908-2774;metodbeteckning;ISO 17294-2;mätvärdetal;0.004;parameter;Mangan;Temperatur vid ankomst;enhet;grader C;kommentar;Ej kylt;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;17.3;parameter;Temperatur vid ankomst;Temperatur vid provtagning;enhet;grader C;lablittera;DM-990908-2774;metodbeteckning;Saknas;mätvärdetal;14.8;parameter;Temperatur vid provtagning;metadata;bedömning;Tjänligt;inlämningsdatum;2010-09-07;inlämningstid;14:15;lablittera;DM-990908-2774;laboratorium;Demo-Laboratoriet;namn;MFR;provplatsid;Demo2 vattenverk;provtagare;DV;provtagningsdatum;2010-09-07;provtagningsorsak;Dricksvatten enligt SLVFS 2001:30;provtagningstid;11:30;provtyp;Utgående;provtypspecifikation;Nej;registertyp;VV1784;specifik provplats;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;år;2010"

        assert result_string == reference_string

    def test_parse_interlab4_quotechar(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Ja",
            "#Decimaltecken=,",
            "#Provadm",
            '"Lablittera";"Namn";"Adress";"Postnr";"Ort";',
            '"DM-990908-2773";"MFR";"PG Vejdes väg 15";"351 96";"Växjö";',
            "#Provdat",
            '"Lablittera";"Metodbeteckning";"Parameter";"Mätvärdetext";"Mätvärdetal";',
            '"DM-990908-2773";"SS-EN ISO 7887-1/4";"Färgtal";;"5";',
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            result = self.importinstance.parse([testfile])
        result_string = ";".join(
            utils_for_tests.dict_to_sorted_list(self.importinstance.parse([testfile]))
        )
        reference_string = "DM-990908-2773;Färgtal;lablittera;DM-990908-2773;metodbeteckning;SS-EN ISO 7887-1/4;mätvärdetal;5;parameter;Färgtal;metadata;adress;PG Vejdes väg 15;lablittera;DM-990908-2773;namn;MFR;ort;Växjö;postnr;351 96"
        assert result_string == reference_string

    def test_parse_interlab4_quotechar_semicolon(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Ja",
            "#Decimaltecken=,",
            "#Provadm",
            '"Lablittera";"Namn";"Adress";"Postnr";"Ort";',
            '"DM-990908-2773";"MFR";"PG ;Vejdes väg 15";"351 96";"Växjö";',
            "#Provdat",
            '"Lablittera";"Metodbeteckning";"Parameter";"Mätvärdetext";"Mätvärdetal";',
            '"DM-990908-2773";"SS-EN ISO 7887-1/4";"Färgtal";;"5";',
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            result = self.importinstance.parse([testfile])
        result_string = "|".join(
            utils_for_tests.dict_to_sorted_list(self.importinstance.parse([testfile]))
        )
        reference_string = "DM-990908-2773|Färgtal|lablittera|DM-990908-2773|metodbeteckning|SS-EN ISO 7887-1/4|mätvärdetal|5|parameter|Färgtal|metadata|adress|PG ;Vejdes väg 15|lablittera|DM-990908-2773|namn|MFR|ort|Växjö|postnr|351 96"

        assert result_string == reference_string

    def test_interlab4_to_table(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;;5;;mg/l Pt;;;;;;;",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Färgtal, 5, 5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    def test_interlab4_to_table_duplicate_kalium(self, mock_getcurrentlocale):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;5;5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;4;4;;mg/l Pt;;;;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium, 4, 4, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium (duplicate 1), 5, 5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print(reference_string)
        print(result_string)
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    def test_interlab4_to_table_duplicate_kalium_between_1_and_2_5(
        self, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;<2,5;2,5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;1,5;1,5;;mg/l Pt;;;;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium, 1.5, 1,5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium (duplicate 1), 2.5, <2,5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print(reference_string)
        print(result_string)
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    def test_interlab4_to_table_duplicate_kalium_largest_value_most_high_resolution(
        self, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;<2,5;2,5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;<1;1;;mg/l Pt;;;;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium, 2.5, <2,5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium (duplicate 1), 1, <1, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print(reference_string)
        print(result_string)
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    def test_interlab4_to_table_duplicate_kalium_2(self, mock_getcurrentlocale):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;3;3;;mg/l Pt;;;±1;;;;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;10;10;;mg/l Pt;;;±0.1;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium, 3, 3, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±1], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium (duplicate 1), 10, 10, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±0.1]]"
        print(reference_string)
        print(result_string)
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    def test_interlab4_to_table_kalium_using_resolution_same_resolution_use_smallest_value(
        self, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;3;3;;mg/l Pt;;;±1;;;;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Kalium;10;10;;mg/l Pt;;;±1;;;;",
            "#Slut",
        )

        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        # reference_string = '[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium, 10, 10, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±1]]'
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium, 3, 3, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±1], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Kalium (duplicate 1), 10, 10, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±1]]"
        print(str(result_string))
        print(str(reference_string))
        assert result_string == reference_string

    def test_interlab4_to_table_matvardetalanm(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;;5;<;mg/l Pt;;;±1;;;;",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Färgtal, 5, <5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±1]]"
        assert result_string == reference_string

    def test_interlab4_to_table_matvardetext_matvardetalanm_no_matvardetal(self):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färgtal;5;;<;mg/l Pt;;;±1;;;;",
            "#Slut",
        )

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Färgtal, 5, <5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15. mätosäkerhet: ±1]]"
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    def test_interlab4_to_table_duplicate_parameters_mg_l_pt(
        self, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Iron;<2,5;2,5;;mg/l Pt;;;;;;;",
            "DM-990908-2773;SS-EN ISO 1234-1/4;Iron;1,5;1,5;;µg/l Pt;;;;;;;",
            "DM-990908-2773;SS-EN ISO 4567-1/4;Iron;35000;35000;;ng/l Pt;;;;;;;",
            "#Slut",
        )

        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 4567-1/4, Iron, 35000, 35000, ng/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Iron (duplicate 1), 2.5, <2,5, mg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 1234-1/4, Iron (duplicate 2), 1.5, 1,5, µg/l Pt, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print("Ref")
        print(str(reference_string))
        print("Test")
        print(str(result_string))
        assert result_string == reference_string

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_interlab4_to_table_duplicate_parameters_mg_l_en(
        self, mock_messagebar, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Iron;<2,5;2,5;;mg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 1234-1/4;Iron;1,5;1,5;;µg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 4567-1/4;Iron;35000;35000;;ng/l;;;;;;;",
            "#Slut",
        )

        mock_getcurrentlocale.return_value = ["en_US", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 4567-1/4, Iron, 35000, 35000, ng/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Iron (duplicate 1), 2.5, <2,5, mg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 1234-1/4, Iron (duplicate 2), 1.5, 1,5, µg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print(str(reference_string))
        print(str(result_string))
        assert result_string == reference_string
        print(f"{mock_messagebar.mock_calls=}")
        assert (
            call.warning(
                log_msg="Duplicate parameter 'Iron' found! Value and unit ('1.5', 'µg/l') was saved as primary parameter out of ('2.5', 'mg/l') and ('1.5', 'µg/l')."
            )
            in mock_messagebar.mock_calls
        )
        assert (
            call.warning(
                log_msg="Duplicate parameter 'Iron' found! Value and unit ('35000', 'ng/l') was saved as primary parameter out of ('1.5', 'µg/l') and ('35000', 'ng/l')."
            )
            in mock_messagebar.mock_calls
        )

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_interlab4_to_table_duplicate_parameters_mg_l_sv(
        self, mock_messagebar, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Iron;<2,5;2,5;;mg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 1234-1/4;Iron;1,5;1,5;;µg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 4567-1/4;Iron;35000;35000;;ng/l;;;;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["sv_SE", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 4567-1/4, Iron, 35000, 35000, ng/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Iron (dubblett 1), 2.5, <2,5, mg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 1234-1/4, Iron (dubblett 2), 1.5, 1,5, µg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print("Ref")
        print(str(reference_string))
        print("Test")
        print(str(result_string))
        assert result_string == reference_string
        print("Mock calls")
        print(f"{mock_messagebar.mock_calls=}")
        assert (
            call.warning(
                log_msg="Duplicate parameter 'Iron' found! Value and unit ('1.5', 'µg/l') was saved as primary parameter out of ('2.5', 'mg/l') and ('1.5', 'µg/l')."
            )
            in mock_messagebar.mock_calls
        )
        assert (
            call.warning(
                log_msg="Duplicate parameter 'Iron' found! Value and unit ('35000', 'ng/l') was saved as primary parameter out of ('1.5', 'µg/l') and ('35000', 'ng/l')."
            )
            in mock_messagebar.mock_calls
        )

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_interlab4_to_table_duplicate_parameters_mg_l_sv_with_color(
        self, mock_messagebar, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Iron;<2,5;2,5;;mg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 1234-1/4;Iron;1,5;1,5;;µg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 4567-1/4;Iron;35000;35000;;ng/l;;;;;;;",
            "DM-990908-2773;testmethod;Färg;svag;;;enhet;;;;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["sv_SE", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 4567-1/4, Iron, 35000, 35000, ng/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Iron (dubblett 1), 2.5, <2,5, mg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 1234-1/4, Iron (dubblett 2), 1.5, 1,5, µg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, testmethod, Färg, None, svag, enhet, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print("Ref")
        print(str(reference_string))
        print("Test")
        print(str(result_string))
        assert result_string == reference_string
        print("Mock calls")
        print(f"{mock_messagebar.mock_calls=}")
        assert (
            call.warning(
                log_msg="Duplicate parameter 'Iron' found! Value and unit ('1.5', 'µg/l') was saved as primary parameter out of ('2.5', 'mg/l') and ('1.5', 'µg/l')."
            )
            in mock_messagebar.mock_calls
        )
        assert (
            call.warning(
                log_msg="Duplicate parameter 'Iron' found! Value and unit ('35000', 'ng/l') was saved as primary parameter out of ('1.5', 'µg/l') and ('35000', 'ng/l')."
            )
            in mock_messagebar.mock_calls
        )

    @mock.patch("midvatten.tools.utils.midvatten_utils.getcurrentlocale")
    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_interlab4_to_table_duplicate_parameters_mg_l_sv_no_float(
        self, mock_messagebar, mock_getcurrentlocale
    ):
        interlab4_lines = (
            "#Interlab",
            "#Version=4.0",
            "#Tecken=UTF-8",
            "#Textavgränsare=Nej",
            "#Decimaltecken=,",
            "#Provadm",
            "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;obsid",
            "DM-990908-2773;MFR;PG Vejdes väg 15;351 96;Växjö;0780;Demoproj;Demo-Laboratoriet;NSG;DV;;Demo1 vattenverk;;Föreskriven regelbunden undersökning enligt SLVFS 2001:30;Dricksvatten enligt SLVFS 2001:30;Utgående;Nej;Tjänligt;;;;2010;2010-09-07;10:15;2010-09-07;14:15;anobsid",
            "#Provdat",
            "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
            "DM-990908-2773;SS-EN ISO 7887-1/4;Färg;svag;;;mg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 1234-1/4;Färg;stark;;;µg/l;;;;;;;",
            "DM-990908-2773;SS-EN ISO 4567-1/4;Färg;obefintlig;;;ng/l;;;;;;;",
            "#Slut",
        )
        mock_getcurrentlocale.return_value = ["sv_SE", "UTF-8"]

        with file_utils.tempinput("\n".join(interlab4_lines), "utf-8") as testfile:
            parsed_result = self.importinstance.parse([testfile])

        result_string = utils_for_tests.create_test_string(
            self.importinstance.to_table(parsed_result)
        )

        # "obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment"
        reference_string = "[[obsid, depth, report, project, staff, date_time, anameth, parameter, reading_num, reading_txt, unit, comment], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 4567-1/4, Färg, None, obefintlig, ng/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 7887-1/4, Färg (dubblett 1), None, svag, mg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15], [anobsid, None, DM-990908-2773, Demoproj, DV, 2010-09-07 10:15:00, SS-EN ISO 1234-1/4, Färg (dubblett 2), None, stark, µg/l, provtagningsorsak: Dricksvatten enligt SLVFS 2001:30. provtyp: Utgående. provtypspecifikation: Nej. bedömning: Tjänligt. provplatsid: Demo1 vattenverk. specifik provplats: Föreskriven regelbunden undersökning enligt SLVFS 2001:30. inlämningsdatum: 2010-09-07. inlämningstid: 14:15]]"
        print("Ref")
        print(str(reference_string))
        print("Test")
        print(str(result_string))
        assert result_string == reference_string

    @mock.patch("midvatten.tools.import_interlab4.tables_columns")
    def test_dest_table_defaults_to_w_qual_lab(self, mock_tables_columns):
        mock_tables_columns.return_value = {}
        self.importinstance.init_gui()
        assert self.importinstance.dest_table == "w_qual_lab"

    @mock.patch("midvatten.tools.import_interlab4.tables_columns")
    def test_dest_table_returns_s_qual_lab_when_selected(self, mock_tables_columns):
        mock_tables_columns.return_value = {"s_qual_lab": []}
        self.importinstance.init_gui()
        self.importinstance.radio_s_qual_lab.setChecked(True)
        assert self.importinstance.dest_table == "s_qual_lab"

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    @mock.patch(
        "midvatten.tools.import_interlab4.midvatten_utils.select_files",
        return_value=[],
    )
    @mock.patch(
        "midvatten.tools.import_interlab4.sql_load_fr_db",
        return_value=(True, []),
    )
    @mock.patch(
        "midvatten.tools.import_interlab4.tables_columns",
        return_value={"s_qual_lab": [], "w_qual_lab": []},
    )
    def test_skip_reports_queries_dest_table(
        self, mock_tables_columns, mock_sql_load, mock_select_files, mock_messagebar
    ):
        print(mock_messagebar.mock_calls)
        self.importinstance.init_gui()
        self.importinstance.skip_imported_reports.setChecked(True)
        self.importinstance.radio_s_qual_lab.setChecked(True)
        self.importinstance.load_files()
        call_sql = mock_sql_load.call_args[0][0]
        assert '"s_qual_lab"' in call_sql
        assert '"w_qual_lab"' not in call_sql


class TestExtractCreateTable:
    def test_extracts_block(self):
        sql = (
            "CREATE TABLE foo (id text);\n"
            "CREATE TABLE s_qual_lab /*comment*/(\n"
            "obsid text not null\n"
            ", primary key(report, parameter)\n"
            ");\n"
            "CREATE TABLE bar (x text);\n"
        )
        result = Interlab4Import._extract_create_table(sql, "s_qual_lab")
        assert "CREATE TABLE s_qual_lab" in result
        assert "primary key(report, parameter)" in result
        assert "CREATE TABLE bar" not in result
        assert "CREATE TABLE foo" not in result

    def test_raises_if_not_found(self):
        with pytest.raises(ValueError, match="CREATE TABLE missing"):
            Interlab4Import._extract_create_table(
                "CREATE TABLE foo (id text);", "missing"
            )


@pytest.mark.spatialite
class TestInterlab4ImportSpatialite(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Integration test for the full Interlab4Import.start_import() flow.

    Exercises parse -> obsid assignment -> to_table -> general_import against a
    real SpatiaLite DB, ensuring all 7 decomposed helper methods of
    MidvDataImporter.general_import execute end-to-end for the interlab4 path.
    """

    _INTERLAB4_LINES = (
        "#Interlab",
        "#Version=4.0",
        "#Tecken=UTF-8",
        "#Textavgränsare=Nej",
        "#Decimaltecken=,",
        "#Provadm",
        "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;"
        "Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;"
        "Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;"
        "Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;"
        "Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
        "DM-1;MFR;;;;;Demoproj;Demo-Lab;NSG;DV;;;VattA;SpA;;Dricksvatten;"
        "Utgående;Nej;Tjänligt;;;2010;2010-09-07;10:15;2010-09-07;14:15;",
        "#Provdat",
        "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;"
        "Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;"
        "Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
        "DM-1;Metod-1;Kalium;;5;;mg/l;;;;;;;",
        "#Slut",
    )

    def _run_interlab4_import(self, mock_messagebar):
        db_utils.sql_alter_db("INSERT INTO obs_points (obsid) VALUES ('Rb1Lab')")

        def _dialog_applies_as_is(
            editor_rows, existing_obsids, reload_callback=None, parent=None
        ):
            fake = mock.MagicMock()
            fake.editor_rows = editor_rows
            fake.outcome = DialogOutcome.APPLY
            fake.exec_ = lambda: None
            return fake

        with file_utils.tempinput(
            "\n".join(self._INTERLAB4_LINES), "utf-8", suffix=".lab"
        ) as filename:

            @mock.patch(
                "midvatten.tools.utils.message_utils.pop_up_info",
                autospec=True,
            )
            @mock.patch(
                "midvatten.tools.utils.dialog_utils.Askuser",
                mocks_for_tests.mock_askuser.get_v,
            )
            @mock.patch("midvatten.tools.utils.common_utils.NotFoundQuestion")
            @mock.patch(
                "midvatten.tools.import_interlab4.ObsidAssignmentDialog",
                side_effect=_dialog_applies_as_is,
            )
            @mock.patch(
                "midvatten.tools.utils.midvatten_utils.select_files",
            )
            def _run(
                self,
                fname,
                mock_select_files,
                mock_dialog,
                mock_notfound,
                mock_popup,
            ):
                mock_notfound.return_value.answer = "ok"
                mock_notfound.return_value.value = "Rb1Lab"
                mock_notfound.return_value.reuse_column = "obsid"
                mock_select_files.return_value = [fname]

                importer = Interlab4Import(self.iface, self.midvatten.ms)
                importer.init_gui()
                # Skip the cache path so the fallback NotFoundQuestion assigns
                # the obsid (mirrors the simplest user flow with a fresh DB).
                importer.use_obsid_assignment_table.setChecked(False)
                importer.load_files()
                importer.start_import(
                    importer.all_lab_results,
                    importer.metadata_filter.get_selected_lablitteras(),
                    importer.ignore_provtagningsorsak.isChecked(),
                )

            _run(self, filename)

        print(f"{mock_messagebar.mock_calls=}")

    @mock.patch("midvatten.tools.utils.message_utils.MessagebarAndLog")
    def test_interlab4_start_import_inserts_into_w_qual_lab(self, mock_messagebar):
        self._run_interlab4_import(mock_messagebar)

        result = db_utils.sql_load_fr_db(
            "SELECT obsid, report, parameter, reading_num, unit"
            " FROM w_qual_lab WHERE obsid='Rb1Lab' ORDER BY parameter"
        )
        assert result[0] is True
        rows = result[1]
        assert len(rows) == 1, f"Expected 1 row in w_qual_lab, got: {rows}"
        assert rows[0][1] == "DM-1"
        assert rows[0][2] == "Kalium"
        assert rows[0][4] == "mg/l"
