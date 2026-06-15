from conan import ConanFile
from conan.tools.files import load, copy, save
from conan.tools.layout import basic_layout
from conan.tools.build import can_run
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
import os


required_conan_version = ">=2.4"


class TestPackage(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    python_requires = "b2-generator-tool/0.1.0"    

    @property
    def _user_config_path(self):
        return os.path.join(self.generators_folder, "user-config.jam")
    
    @property
    def _project_config_path(self):
        return os.path.join(self.generators_folder, "project-config.jam")

    def export_sources(self):
        copy(self, "Jamfile.jam", self.recipe_folder, self.export_sources_folder)
        copy(self, "*.cpp", self.recipe_folder, self.export_sources_folder)
        copy(self, "*.hpp", self.recipe_folder, self.export_sources_folder)

    def layout(self):
        basic_layout(self)

    def generate(self):
        b2generator = self.python_requires["b2-generator-tool"].module.B2Generator(self)
        b2generator.generate()

        deps = self.dependencies[self.tested_reference_str]
        include_paths = " ".join([f'<include>{p}' for p in deps.cpp_info.includedirs])
        lib_paths = " ".join([f'<library-path>{p}' for p in deps.cpp_info.libdirs])
        libs = " ".join([f'-l{lib}' for lib in deps.cpp_info.libs])
        
        jamroot = f"""
project test_package
 : requirements
   {include_paths}
   {lib_paths}
;

exe test_package : {self.source_folder}/test_package.cpp : <linkflags>"{libs}" ;
"""
        save(self, os.path.join(self.build_folder, "Jamroot"), jamroot)

        env = VirtualBuildEnv(self)
        env.generate()
        env_run = VirtualRunEnv(self)
        env_run.generate()

    def requirements(self):
        self.requires(self.tested_reference_str)

    def build_requirements(self):
        self.tool_requires("b2/[>=5.2 <6]")        

    def build(self):
        self.run(f"b2 {self.build_folder} -a -d2 --debug-configuration --layout=system --user-config={self._user_config_path} --project-config={self._project_config_path} --build-dir={self.build_folder} --prefix={self.package_folder} --abbreviate-paths")

    def test(self):
        if can_run(self):
            # find test_package binary in the build folder
            for root, _, files in os.walk(self.build_folder):
                if "test_package" in files or "test_package.exe" in files:
                    bin_path = os.path.join(root, "test_package" if "test_package" in files else "test_package.exe")
                    break
            self.run(bin_path, env="conanrun")