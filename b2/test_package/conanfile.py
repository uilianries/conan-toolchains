from conan import ConanFile
from conan.tools.files import load, copy, chdir
from conan.tools.layout import basic_layout
from conan.tools.build import can_run
from conan.tools.env import VirtualBuildEnv, VirtualRunEnv
import os

class TestPackage(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    python_requires = "tested_reference_str"

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
        copy(self, "Jamfile.jam", self.source_folder, self.build_folder)
        copy(self, "main.cpp", self.source_folder, self.build_folder)
        user_config_path = os.path.join(self.generators_folder, "user-config.jam")
        project_config_path = os.path.join(self.generators_folder, "project-config.jam")
        self.run(f"b2 release -a -d2 --debug-configuration --layout=system --user-config={user_config_path} --project-config={project_config_path} --build-folder={self.build_folder} cxxstd=17 --abbreviate-paths")

    def test(self):
        user_config = os.path.join(self.generators_folder, "user-config.jam")
        assert os.path.exists(user_config)
        content = load(self, user_config)
        self.output.info(f"user-config.jam content:\n{content}")

        project_config = os.path.join(self.generators_folder, "project-config.jam")
        assert os.path.exists(project_config)
        content = load(self, project_config)
        self.output.info(f"project-config.jam content:\n{content}")

        if can_run(self):
            for root, _, files in os.walk(self.build_folder):
                if "hello" in files:
                    bin_path = os.path.join(root, "hello")
                    break
            self.run(bin_path, env="conanrun")