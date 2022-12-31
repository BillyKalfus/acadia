f.write(f"read_vhdl {self._hdl_filename}\n")
            set file "$origin_dir/../pyacadia/tests/tmp/python_modules.vhd"
            set file [file normalize $file]
            set file_obj [get_files -of_objects [get_filesets sources_1] [list "*$file"]]
            set_property -name "file_type" -value "VHDL" -objects $file_obj
            set_property -name "is_enabled" -value "1" -objects $file_obj
            set_property -name "is_global_include" -value "0" -objects $file_obj
            set_property -name "library" -value "xil_defaultlib" -objects $file_obj
            set_property -name "path_mode" -value "RelativeFirst" -objects $file_obj
            set_property -name "used_in" -value "synthesis simulation" -objects $file_obj
            set_property -name "used_in_simulation" -value "1" -objects $file_obj
            set_property -name "used_in_synthesis" -value "1" -objects $file_obj
            f.write(f"update_module_reference [get_ips]\n")