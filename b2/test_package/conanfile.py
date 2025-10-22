from conan import ConanFile
from conan.tools.files import load
import os

class TestPackage(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    python_requires = "tested_reference_str"

    def test(self):
        b2generator = self.python_requires["b2-generator-tool"].module.B2Generator(self)
        b2generator.generate()
        user_config = os.path.join(self.generators_folder, "user-config.jam")
        assert os.path.exists(user_config)
        content = load(self, user_config)
        self.output.info(f"user-config.jam content:\n{content}")




        