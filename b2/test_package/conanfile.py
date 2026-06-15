from conan import ConanFile
from conan.tools.layout import basic_layout
import os


class TestPackageConan(ConanFile):
    settings = "os", "arch", "compiler", "build_type"
    python_requires = "tested_reference_str"

    def layout(self):
        basic_layout(self)

    def generate(self):
        b2generator = self.python_requires["b2-generator-tool"].module.B2Generator(self)
        b2generator.generate()

    def test(self):
        user_config_path = os.path.join(self.generators_folder, "user-config.jam")
        project_config_path = os.path.join(self.generators_folder, "project-config.jam")

        assert os.path.isfile(user_config_path), f"{user_config_path} must exist"
        assert os.path.isfile(project_config_path), f"{project_config_path} must exist"
        