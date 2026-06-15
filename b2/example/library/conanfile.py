from conan import ConanFile
from conan.tools.files import load, copy, chdir
from conan.tools.layout import basic_layout
from conan.tools.build import can_run
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
from conan.tools.cmake import CMake, CMakeToolchain, cmake_layout
import os


required_conan_version = ">=2.4"


class Library(ConanFile):
    name = "mylib"
    version = "0.1.0"
    license = "MIT"
    settings = "os", "compiler", "build_type", "arch"
    package_type = "library"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = {"shared": False, "fPIC": True}
    implements = ["auto_shared_fpic"]
    languages = "C++"
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

        env = VirtualBuildEnv(self)
        env.generate()
        env_run = VirtualRunEnv(self)
        env_run.generate()

    def build_requirements(self):
        self.tool_requires("b2/[>=5.2 <6]")        

    def build(self):
        with chdir(self, self.source_folder):
            self.run(f"b2 {self.source_folder} install --layout=system --user-config={self._user_config_path} --project-config={self._project_config_path} --build-dir={self.build_folder} --prefix={self.package_folder} --abbreviate-paths -a -d2 --debug-configuration")

    def package(self):
        pass

    def package_info(self):
        self.cpp_info.libs = ["mylib"]