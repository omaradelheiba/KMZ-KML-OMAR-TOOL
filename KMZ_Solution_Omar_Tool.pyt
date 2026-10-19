# -*- coding: utf-8 -*-
import arcpy
import os
import re
import uuid
import html
from html.parser import HTMLParser


class SmartPopupParser(HTMLParser):
    """
    محرك ذكي لتحليل كود HTML المستخرج من حقل PopupInfo بجميع أنماطه:
    1. النمط النصي (Inline): <b>رقم الطلب:</b> 2069084<br/>
    2. نمط الجداول (Tables): <tr><td>رقم الطلب</td><td>2069084</td></tr>
    3. النصوص المفصولة بأسطر ونقطتين (Key : Value)
    """
    def __init__(self):
        super().__init__()
        self.attributes = {}
        self.in_bold = False
        self.bold_buffer = []
        self.current_bold_key = None
        self.val_buffer = []
        self.in_td = False
        self.td_buffer = []
        self.current_row_cells = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ('b', 'strong'):
            self._flush_bold_pair()
            self.in_bold = True
            self.bold_buffer = []
        elif tag == 'br':
            self._flush_bold_pair()
        elif tag == 'tr':
            self.current_row_cells = []
        elif tag in ('td', 'th'):
            self.in_td = True
            self.td_buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('b', 'strong'):
            self.in_bold = False
            raw_key = ''.join(self.bold_buffer).strip()
            clean_key = re.sub(r'^[:\-\s]+|[:\-\s]+$', '', raw_key).strip()
            if clean_key:
                self.current_bold_key = clean_key
                self.val_buffer = []
        elif tag in ('td', 'th'):
            self.in_td = False
            cell_text = ''.join(self.td_buffer).strip()
            self.current_row_cells.append(cell_text)
        elif tag in ('tr', 'p', 'div'):
            self._flush_bold_pair()
            if tag == 'tr' and len(self.current_row_cells) == 2:
                k = re.sub(r'^[:\-\s]+|[:\-\s]+$', '', self.current_row_cells[0]).strip()
                v = self.current_row_cells[1].strip()
                if k and k not in self.attributes and len(k) < 100:
                    self.attributes[k] = v

    def handle_data(self, data):
        if self.in_bold:
            self.bold_buffer.append(data)
        elif self.current_bold_key is not None:
            self.val_buffer.append(data)
        if self.in_td:
            self.td_buffer.append(data)

    def _flush_bold_pair(self):
        if self.current_bold_key is not None:
            val = ''.join(self.val_buffer).strip()
            val = re.sub(r'^[:\-\s]+', '', val).strip()
            self.attributes[self.current_bold_key] = val
            self.current_bold_key = None
            self.val_buffer = []

    def parse_popup(self, raw_html):
        if not raw_html or not str(raw_html).strip():
            return {}
        clean_html = html.unescape(str(raw_html))
        self.feed(clean_html)
        self._flush_bold_pair()
        
        if not self.attributes:
            text_lines = re.sub(r'<br\s*/?>', '\n', clean_html, flags=re.IGNORECASE)
            text_lines = re.sub(r'<[^>]+>', '', text_lines)
            for line in text_lines.splitlines():
                if ':' in line:
                    parts = line.split(':', 1)
                    k = parts[0].strip()
                    v = parts[1].strip()
                    if k and len(k) < 80:
                        self.attributes[k] = v
        return self.attributes


class Toolbox(object):
    def __init__(self):
        self.label = "KMZ/KML Solution Omar Tool"
        self.alias = "KMZSolutionOmarTool"
        self.tools = [KMZSolutionOmarTool]


class KMZSolutionOmarTool(object):
    def __init__(self):
        self.label = "KMZ/KML Solution Omar Tool"
        self.description = (
            "أداة احترافية لتحويل ملفات KMZ/KML مباشرة إلى الخريطة مع تفكيك بيانات "
            "الـ Popup تلقائياً إلى أعمدة مستقلة في الـ Attribute Table دون أخطاء قفل الجداول."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        # 1. ملف الـ KMZ أو KML المدخل (الوحيد المطلوب إجبارياً)
        param_in_kmz = arcpy.Parameter(
            displayName="ملف الـ KMZ / KML (Input File)",
            name="in_kmz",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        param_in_kmz.filter.list = ['kmz', 'kml']

        # 2. اسم الطبقة في الخريطة (يتولد تلقائياً من اسم الملف)
        param_layer_name = arcpy.Parameter(
            displayName="اسم الطبقة في الخريطة (Output Layer Name)",
            name="layer_name",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )

        # 3. مكان حفظ البيانات (يمتلئ تلقائياً بقاعدة بيانات المشروع Default.gdb)
        param_out_workspace = arcpy.Parameter(
            displayName="قاعدة بيانات الحفظ (تلقائي في المشروع الحالي)",
            name="out_workspace",
            datatype=["DEWorkspace", "DEFolder"],
            parameterType="Optional",
            direction="Input"
        )
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            if aprx.defaultGeodatabase:
                param_out_workspace.value = aprx.defaultGeodatabase
        except Exception:
            pass

        # 4. خيار حذف حقل كود الـ HTML بعد استخراج الأعمدة
        param_del_popup = arcpy.Parameter(
            displayName="حذف عمود الكود الأصلي (PopupInfo) بعد استخراج الأعمدة النظيفة",
            name="delete_popup_field",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        param_del_popup.value = True

        # 5. ليبل التوقيع في منتصف أسفل الأداة
        param_signature = arcpy.Parameter(
            displayName=" ",
            name="developer_signature",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )
        param_signature.value = "                     ★  Developed By Omar Adel Heiba  ★"
        param_signature.enabled = False

        return [
            param_in_kmz,
            param_layer_name,
            param_out_workspace,
            param_del_popup,
            param_signature
        ]

    def updateParameters(self, parameters):
        # بمجرد اختيار ملف الـ KMZ يكتب اسم الطبقة أوتوماتيك
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            kmz_path = parameters[0].valueAsText
            if kmz_path:
                base_name = os.path.splitext(os.path.basename(kmz_path))[0]
                clean_name = re.sub(r'[^\w\u0600-\u06FF]', '_', base_name).strip('_')
                clean_name = re.sub(r'_+', '_', clean_name)
                if not clean_name or clean_name[0].isdigit():
                    clean_name = f"KMZ_{clean_name}"
                parameters[1].value = clean_name

        # ضمان ملء قاعدة البيانات الافتراضية لو فاضية
        if not parameters[2].valueAsText:
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                if aprx.defaultGeodatabase:
                    parameters[2].value = aprx.defaultGeodatabase
            except Exception:
                pass

        parameters[4].value = "                     ★  Developed By Omar Adel Heiba  ★"
        return

    def updateMessages(self, parameters):
        return

    def _create_safe_field_name(self, raw_key, existing_fields, target_fc):
        """
        إنشاء اسم برمجي آمن (Field Name) لتجنب أي خطأ في قواعد البيانات
        مع وضع الاسم العربي الأصلي بالكامل في الـ Alias
        """
        clean_name = re.sub(r'[^\w\u0600-\u06FF]', '_', raw_key).strip('_')
        clean_name = re.sub(r'_+', '_', clean_name)
        
        if not clean_name or clean_name[0].isdigit():
            clean_name = f"F_{clean_name}" if clean_name else "Field"
            
        valid_name = arcpy.ValidateFieldName(clean_name[:45], os.path.dirname(target_fc))
        if not valid_name or valid_name[0].isdigit():
            valid_name = f"F_{valid_name}"
            
        final_name = valid_name
        counter = 1
        while final_name.lower() in existing_fields:
            final_name = f"{valid_name[:40]}_{counter}"
            counter += 1
            
        existing_fields.add(final_name.lower())
        return final_name

    def _resolve_target_gdb(self, workspace_path, layer_name, kmz_path):
        """
        تجهيز قاعدة البيانات النهائية القابلة للتعديل (Editable Geodatabase)
        """
        if not workspace_path:
            try:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                if aprx.defaultGeodatabase and arcpy.Exists(aprx.defaultGeodatabase):
                    return aprx.defaultGeodatabase
            except Exception:
                pass
            workspace_path = os.path.dirname(kmz_path)

        if workspace_path.lower().endswith(".gdb") and arcpy.Exists(workspace_path):
            return workspace_path

        # لو المستخدم اختار مجلد عادي (Folder)، ننشئ جواه File GDB نظيفة قابلة للتعديل
        gdb_name = f"{layer_name}_Data.gdb"
        gdb_full_path = os.path.join(workspace_path, gdb_name)
        if not arcpy.Exists(gdb_full_path):
            arcpy.management.CreateFileGDB(workspace_path, gdb_name)
        return gdb_full_path

    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True

        in_kmz = parameters[0].valueAsText
        layer_name = parameters[1].valueAsText
        out_workspace = parameters[2].valueAsText
        delete_popup = parameters[3].value

        arcpy.AddMessage("\n" + "═" * 68)
        arcpy.AddMessage("          🚀  KMZ/KML SOLUTION OMAR TOOL - ENGINE STARTED  🚀")
        arcpy.AddMessage("                   Developed By Omar Adel Heiba")
        arcpy.AddMessage("═" * 68)

        # 1. استخراج ملف الـ KMZ في مجلد مؤقت (Scratch) لتجنب قفل الجداول ERROR 000499
        arcpy.AddMessage("\n[1/4] ⏳ جاري فك ضغط وقراءة ملف الـ KMZ...")
        scratch_folder = arcpy.env.scratchFolder
        if not scratch_folder or not os.path.exists(scratch_folder):
            scratch_folder = os.path.dirname(in_kmz)

        temp_id = f"tmp_kml_{uuid.uuid4().hex[:6]}"
        arcpy.conversion.KMLToLayer(in_kmz, scratch_folder, temp_id, "NO_GROUNDOVERLAY")

        temp_gdb = os.path.join(scratch_folder, f"{temp_id}.gdb")
        temp_placemarks = os.path.join(temp_gdb, "Placemarks")

        if not arcpy.Exists(temp_gdb):
            arcpy.AddError("❌ فشل في قراءة ملف الـ KMZ.")
            return

        source_ws = temp_placemarks if arcpy.Exists(temp_placemarks) else temp_gdb
        arcpy.env.workspace = source_ws
        raw_fcs = arcpy.ListFeatureClasses()

        if not raw_fcs:
            arcpy.AddWarning("⚠️ لم يتم العثور على أي أشكال هندسية داخل ملف الـ KMZ.")
            return

        arcpy.AddMessage(f"      ✔ تم استخراج ({len(raw_fcs)}) طبقة رسم هندسي بنجاح.")

        # 2. نسخ الطبقات إلى قاعدة بيانات المشروع القابلة للتعديل (حل جذري لمشكلة 000499)
        target_gdb = self._resolve_target_gdb(out_workspace, layer_name, in_kmz)
        arcpy.AddMessage(f"\n[2/4] 🔍 جاري بناء الطبقات القابلة للتعديل وتفكيك أكواد الـ Popup...")

        created_layers_info = []

        for fc in raw_fcs:
            src_fc_path = os.path.join(source_ws, fc)
            
            # تسمية الطبقة النهائية
            if len(raw_fcs) == 1:
                out_fc_name = arcpy.ValidateTableName(layer_name, target_gdb)
                display_layer_title = layer_name
            else:
                out_fc_name = arcpy.ValidateTableName(f"{layer_name}_{fc}", target_gdb)
                display_layer_title = f"{layer_name} - {fc}"

            target_fc_path = os.path.join(target_gdb, out_fc_name)
            if arcpy.Exists(target_fc_path):
                arcpy.management.Delete(target_fc_path)

            # نسخ الطبقة إلى قاعدة بيانات قابلة للتعديل 100%
            arcpy.conversion.FeatureClassToFeatureClass(src_fc_path, target_gdb, out_fc_name)

            # إزالة أي قفل وتحليل حقل PopupInfo
            fc_fields = [f.name for f in arcpy.ListFields(target_fc_path)]
            existing_fields_lower = {f.lower() for f in fc_fields}

            if "PopupInfo" in fc_fields:
                discovered_keys = []
                max_lengths = {}
                parsed_rows_cache = {}

                with arcpy.da.SearchCursor(target_fc_path, ["OID@", "PopupInfo"]) as s_cursor:
                    for oid, popup_html in s_cursor:
                        parser = SmartPopupParser()
                        extracted_dict = parser.parse_popup(popup_html)
                        parsed_rows_cache[oid] = extracted_dict
                        
                        for k, v in extracted_dict.items():
                            if k not in discovered_keys:
                                discovered_keys.append(k)
                            val_len = len(str(v)) if v else 0
                            if val_len > max_lengths.get(k, 0):
                                max_lengths[k] = val_len

                if discovered_keys:
                    arcpy.AddMessage(f"\n   📌 الطبقة [{fc}] -> جاري إنشاء ({len(discovered_keys)}) أعمدة جديدة:")
                    key_to_fieldname = {}

                    for key in discovered_keys:
                        safe_field_name = self._create_safe_field_name(key, existing_fields_lower, target_fc_path)
                        key_to_fieldname[key] = safe_field_name
                        field_length = max(255, min(max_lengths.get(key, 255) + 100, 4000))
                        
                        arcpy.management.AddField(
                            in_table=target_fc_path,
                            field_name=safe_field_name,
                            field_type="TEXT",
                            field_length=field_length,
                            field_alias=key
                        )
                        arcpy.AddMessage(f"      ➕ تم إنشاء العمود: [{key}]")

                    # 3. تعبئة البيانات في الأعمدة الجديدة
                    arcpy.AddMessage(f"\n[3/4] ⚡ جاري تسكين البيانات داخل السجلات للطبقة [{fc}]...")
                    new_field_names = [key_to_fieldname[k] for k in discovered_keys]
                    cursor_fields = ["OID@"] + new_field_names

                    updated_count = 0
                    with arcpy.da.UpdateCursor(target_fc_path, cursor_fields) as u_cursor:
                        for row in u_cursor:
                            oid = row[0]
                            row_data = parsed_rows_cache.get(oid, {})
                            if row_data:
                                for idx, key in enumerate(discovered_keys):
                                    row[idx + 1] = row_data.get(key, None)
                                u_cursor.updateRow(row)
                                updated_count += 1

                    arcpy.AddMessage(f"      ✔ تم تحديث ({updated_count}) شيب ببيانات البوب أب بنجاح.")

                # حذف عمود الكود القديم لو المستخدم معلم على الخيار
                if delete_popup:
                    try:
                        arcpy.management.DeleteField(target_fc_path, ["PopupInfo"])
                    except Exception:
                        pass

            created_layers_info.append((target_fc_path, display_layer_title))

        # 4. إضافة الطبقة مباشرة إلى الخريطة المفتوحة
        arcpy.AddMessage("\n[4/4] 🗺️ جاري إدراج الطبقة مباشرة في الخريطة المفتوحة...")
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            active_map = aprx.activeMap
            if active_map:
                for fc_path, lyr_title in created_layers_info:
                    added_lyr = active_map.addDataFromPath(fc_path)
                    try:
                        added_lyr.name = lyr_title
                    except Exception:
                        pass
                arcpy.AddMessage("      ✔ نزلت الطبقة في الخريطة بنجاح! افتح الـ Attribute Table الآن.")
            else:
                arcpy.AddWarning("      ⚠️ لا توجد خريطة نشطة مفتوحة، تم حفظ الطبقة في قاعدة بيانات المشروع.")
        except Exception as e:
            arcpy.AddWarning(f"      ⚠️ تنبيه أثناء الإضافة للخريطة: {str(e)}")

        # تنظيف الملفات المؤقتة
        try:
            if arcpy.Exists(temp_gdb):
                arcpy.management.Delete(temp_gdb)
            temp_lyrx = os.path.join(scratch_folder, f"{temp_id}.lyrx")
            if arcpy.Exists(temp_lyrx):
                arcpy.management.Delete(temp_lyrx)
        except Exception:
            pass

        arcpy.AddMessage("\n" + "═" * 68)
        arcpy.AddMessage("          ✅  تمت العملية بنجاح! الطبقة والبيانات جاهزة بالخريطة  ✅")
        arcpy.AddMessage("                   Developed By Omar Adel Heiba")
        arcpy.AddMessage("═" * 68 + "\n")
        return