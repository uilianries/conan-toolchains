import os
from conan import ConanFile
from conan.tools.files import save
from conan.tools.build import build_jobs
from conan.tools.env import VirtualBuildEnv, Environment


class B2Generator:
    """
    B2 (Boost.Build) toolchain generator for Conan.
    Generates a user-config.jam file with toolset configuration and a 
    conan_b2_toolchain.jam file with dependency information.
    """

    def __init__(self, conanfile):
        self._conanfile = conanfile
        self.user_config_jam = None
        self.project_config_jam = None        
        
    def generate(self):
        """Generate the B2 toolchain files"""
        # Generate user-config.jam with toolset configuration
        self._generate_user_config()
        
        # Generate project-config.jam with Conan-specific settings
        self._generate_project_config()
        
    def _get_toolset(self):
        """Determine the B2 toolset from Conan settings"""
        compiler = self._conanfile.settings.get_safe("compiler")
        
        toolset_map = {
            "gcc": "gcc",
            "clang": "clang",
            "apple-clang": "clang",
            "msvc": "msvc",
            "intel-cc": "intel",
        }
        
        return toolset_map.get(compiler, compiler)
    
    def _get_compiler_executables(self):
        """Get compiler executables from environment or settings"""
        compiler = self._conanfile.settings.get_safe("compiler")

        compiler_executables = self._conanfile.conf.get("tools.build:compiler_executables", check_type=dict, default={})
        conf_cc = compiler_executables.get("c")
        conf_cxx = compiler_executables.get("cpp")
        
        # Check for environment variables first
        virtualenv = VirtualBuildEnv(self._conanfile)
        virtualenv_cc = virtualenv.vars().get("CC")
        virtualenv_cxx = virtualenv.vars().get("CXX")
        
        env_cc = os.getenv("CC")
        env_cxx = os.getenv("CXX")

        cc = conf_cc or virtualenv_cc or env_cc
        cxx = conf_cxx or virtualenv_cxx or env_cxx

        self._conanfile.output.info(f"Detected compiler executables: CC={cc}, CXX={cxx}")

        if not cc or not cxx:
            # Provide defaults based on compiler
            if compiler == "gcc":
                cc = cc or "gcc"
                cxx = cxx or "g++"
            elif compiler in ["clang", "apple-clang"]:
                cc = cc or "clang"
                cxx = cxx or "clang++"
            elif compiler == "msvc":
                # MSVC is auto-detected by B2
                return None, None
                
        return cc, cxx
    
    def _get_architecture(self):
        """Get B2 architecture from Conan settings"""
        arch = self._conanfile.settings.get_safe("arch")
        
        arch_map = {
            "x86": "x86",
            "x86_64": "x86",
            "armv7": "arm",
            "armv8": "arm",
            "armv8_32": "arm",
            "armv8.3": "arm",
        }
        
        return arch_map.get(arch, arch)
    
    def _get_address_model(self):
        """Get B2 address-model from Conan settings"""
        arch = self._conanfile.settings.get_safe("arch")
        
        if arch in ["x86_64", "armv8", "armv8.3"]:
            return "64"
        elif arch in ["x86", "armv7", "armv8_32"]:
            return "32"
        
        return None
    
    def _generate_user_config(self):
        """Generate user-config.jam with toolset configuration"""
        toolset = self._get_toolset()
        cc, cxx = self._get_compiler_executables()
        
        content = ["# Conan generated user-config.jam", ""]
        
        if toolset and toolset != "msvc":
            # For non-MSVC compilers, configure the toolset
            version = self._conanfile.settings.get_safe("compiler.version")
            
            config_line = f"using {toolset}"
            if version:
                config_line += f" : {version}"
            if cxx:
                config_line += f" : {cxx}"
            config_line += " ;"
            
            content.append(config_line)
        elif toolset == "msvc":
            # MSVC configuration
            version = self._conanfile.settings.get_safe("compiler.version")
            if version:
                content.append(f"using msvc : {version} ;")
            else:
                content.append("using msvc ;")
        
        content.append("")
        
        self.user_config_jam = "\n".join(content)
        save(self._conanfile, "user-config.jam", self.user_config_jam)
        
    def _generate_project_config(self):
        """Generate project-config.jam with Conan settings and dependencies"""
        content = ["# Conan generated project-config.jam", ""]
        
        # Add build settings
        build_type = self._conanfile.settings.get_safe("build_type")
        if build_type:
            variant = build_type.lower()
            content.append(f"# Build type: {variant}")
        
        # Add architecture settings
        arch = self._get_architecture()
        address_model = self._get_address_model()
        
        if arch:
            content.append(f"# Architecture: {arch}")
        if address_model:
            content.append(f"# Address model: {address_model}")
        
        content.append("")
        
        # Add dependency information
        content.append("# Conan dependencies")
        
        for dep in self._conanfile.dependencies.values():
            dep_name = dep.ref.name
            
            # Include paths
            if dep.cpp_info.includedirs:
                for include_dir in dep.cpp_info.includedirs:
                    content.append(f"# {dep_name} include: {include_dir}")
            
            # Library paths
            if dep.cpp_info.libdirs:
                for lib_dir in dep.cpp_info.libdirs:
                    content.append(f"# {dep_name} libdir: {lib_dir}")
            
            # Libraries
            if dep.cpp_info.libs:
                for lib in dep.cpp_info.libs:
                    content.append(f"# {dep_name} lib: {lib}")
        
        content.append("")
        
        # Generate path-constant for dependencies
        content.append("# Dependency paths")
        for dep in self._conanfile.dependencies.values():
            dep_name = dep.ref.name.upper().replace("-", "_")
            if dep.cpp_info.includedirs:
                include_path = dep.cpp_info.includedirs[0]
                content.append(f"path-constant {dep_name}_INCLUDE : {include_path} ;")
            if dep.cpp_info.libdirs:
                lib_path = dep.cpp_info.libdirs[0]
                content.append(f"path-constant {dep_name}_LIB : {lib_path} ;")
        
        content.append("")
        
        self.project_config_jam = "\n".join(content)
        save(self._conanfile, "project-config.jam", self.project_config_jam)
    
    def _get_b2_flags(self):
        """Get B2 command line flags from Conan settings"""
        flags = []
        
        # Variant (build type)
        build_type = self._conanfile.settings.get_safe("build_type")
        if build_type:
            flags.append(f"variant={build_type.lower()}")
        
        # Threading
        flags.append("threading=multi")
        
        # Link type
        if self._conanfile.options.get_safe("shared"):
            flags.append("link=shared")
        else:
            flags.append("link=static")
        
        # Runtime linking (Windows)
        runtime = self._conanfile.settings.get_safe("compiler.runtime")
        if runtime:
            if "MT" in runtime:
                flags.append("runtime-link=static")
            else:
                flags.append("runtime-link=shared")
        
        # Address model
        address_model = self._get_address_model()
        if address_model:
            flags.append(f"address-model={address_model}")
        
        # Architecture
        arch = self._get_architecture()
        if arch:
            flags.append(f"architecture={arch}")
        
        # Jobs
        jobs = build_jobs(self._conanfile)
        if jobs:
            flags.append(f"-j{jobs}")
        
        return flags
    
    def get_b2_command_flags(self):
        """
        Get the B2 command line flags as a list.
        Useful for passing to b2 command in build() method.
        """
        return self._get_b2_flags()
    
    def get_b2_command_flags_str(self):
        """
        Get the B2 command line flags as a string.
        Useful for passing to b2 command in build() method.
        """
        return " ".join(self._get_b2_flags())


class B2ToolGenerator(ConanFile):
    name = "b2-generator-tool"
    version = "0.1.0"

    def package_info(self):
        self.generator_info = [B2Generator]