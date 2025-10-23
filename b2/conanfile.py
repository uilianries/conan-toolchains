import os
import re
from conan import ConanFile
from conan.tools.files import save
from conan.tools.build import build_jobs
from conan.tools.microsoft import is_msvc, MSBuildToolchain
from conan.tools.apple import is_apple_os, XCRun, to_apple_arch
from conan.tools.scm import Version
from conan.tools.env import VirtualBuildEnv, Environment
from conan.tools.build import cross_building
from conan.errors import ConanException


class B2Generator:
    """
    B2 (Boost.Build) toolchain generator for Conan.
    Generates a user-config.jam file with toolset configuration and a 
    conan_b2_toolchain.jam file with dependency information.
    """
    USER_CONFIG = "user-config.jam"
    PROJECT_CONFIG = "project-config.jam"


    def __init__(self, conanfile):
        self._conanfile = conanfile

    def _validate(self):
        """Validate required settings for B2 generation"""
        if not self._conanfile.settings.get_safe("compiler"):
            raise ConanException("B2Generator requires 'compiler' setting to be defined.")
        if not self._conanfile.settings.get_safe("build_type"):
            raise ConanException("B2Generator requires 'build_type' setting to be defined.")
        if not self._conanfile.settings.get_safe("arch"):
            raise ConanException("B2Generator requires 'arch' setting to be defined.")
        if not self._conanfile.settings.get_safe("os"):
            raise ConanException("B2Generator requires 'os' setting to be defined.")

    def generate(self):
        """Generate the B2 toolchain files"""
        self._validate()

        # Generate user-config.jam with toolset configuration
        self._generate_user_config()
        
        # Generate project-config.jam with Conan-specific settings
        self._generate_project_config()

    def _get_b2_module_name(self, dependency):
        name = dependency.ref.name
        # b2 --help-internal shows that module names are lowercase
        known_modules = ["bison", "boost", "bzip2", "gettext", "lex", "libjpeg", "libpng", "libtiff",
                         "lzma", "mpi", "openssl", "pkg-config", "python", "qt", "qt3", "qt4",
                         "qt5", "saxonhe", "scanner", "tntnet", "zlib", "zstd"]
        if name.lower() in known_modules:
            return name.lower()
        mapped_modules = {"xz_utils": "lzma",}
        return mapped_modules.get(name)

    def _ar(self):
        ar = VirtualBuildEnv(self._conanfile).vars().get("AR")
        if ar:
            return ar.replace("\\", "/")
        if is_apple_os(self._conanfile) and self._conanfile.settings.compiler == "apple-clang":
            return XCRun(self._conanfile).ar.replace("\\", "/")
        return None

    def _build_cross_flags(self):
        flags = []
        if not cross_building(self._conanfile):
            return flags
        arch = self._conanfile.settings.arch

        if arch.startswith("arm"):
            if "hf" in arch:
                flags.append("-mfloat-abi=hard")
        elif self._conanfile.settings.os == "Emscripten":
            pass
        elif arch in ["x86", "x86_64"]:
            pass
        elif arch.startswith("ppc"):
            pass
        elif arch.startswith("mips"):
            pass
        elif arch.startswith("riscv"):
            pass
        else:
            self._conanfile.output.info(f"Unable to detect the appropriate ABI for {arch} architecture.")
        self._conanfile.output.debug(f"Cross building flags: {flags}")
        return flags

    def _is_apple_embedded_platform(self):
        return self._conanfile.settings.os in ["iOS", "watchOS", "tvOS"]

    def _ranlib(self):
        ranlib = VirtualBuildEnv(self._conanfile).vars().get("RANLIB")
        if ranlib:
            return ranlib.replace("\\", "/")
        if is_apple_os(self._conanfile) and self._conanfile.settings.compiler == "apple-clang":
            return XCRun(self._conanfile).ranlib.replace("\\", "/")
        return None

    def _b2_os(self):
        return {
            "Windows": "windows",
            "WindowsStore": "windows",
            "Linux": "linux",
            "Android": "android",
            "Macos": "darwin",
            "iOS": "iphone",
            "watchOS": "iphone",
            "tvOS": "appletv",
            "FreeBSD": "freebsd",
            "SunOS": "solaris",
        }.get(str(self._conanfile.settings.os))
        
    def _get_toolset(self):

        if is_msvc(self._conanfile):
            return "clang-win" if self._conanfile.settings.compiler.toolset == "ClangCL" else "msvc"
        if self._conanfile.settings.os == "Windows" and self._conanfile.settings.compiler == "clang":
            return "clang-win"
        if self._conanfile.settings.os == "Emscripten" and self._conanfile.settings.compiler in ("clang", "emcc"):
            return "emscripten"
        if self._conanfile.settings.compiler == "gcc" and is_apple_os(self._conanfile):
            return "darwin"
        if self._conanfile.settings.compiler == "apple-clang":
            return "clang-darwin"
        if self._conanfile.settings.os == "Android" and self._conanfile.settings.compiler == "clang":
            return "clang-linux"
        if self._conanfile.settings.compiler in ["clang", "gcc"]:
            return str(self._conanfile.settings.compiler)
        if self._conanfile.settings.compiler == "sun-cc":
            return "sunpro"
        if "intel" in str(self._conanfile.settings.compiler):
            return {
                "Macos": "intel-darwin",
                "Windows": "intel-win",
                "Linux": "intel-linux",
            }[str(self._conanfile.settings.os)]

        return str(self._conanfile.settings.compiler)
    
    def _get_toolset_version(self):
        """Get toolset version from settings"""
        toolset = MSBuildToolchain(self._conanfile).toolset
        if toolset:
            match = re.match(r"v(\d+)(\d)$", toolset)
            if match:
                return f"{match.group(1)}.{match.group(2)}"
        return Version(self._conanfile.settings.compiler.version).major

    def _get_compiler_executables(self):
        """Get compiler executables from environment or settings"""
        compiler = self._conanfile.settings.compiler

        compiler_executables = self._conanfile.conf.get("tools.build:compiler_executables", check_type=dict, default={})
        conf_cc = compiler_executables.get("c")
        conf_cxx = compiler_executables.get("cpp")
        
        virtualenv = VirtualBuildEnv(self._conanfile)
        virtualenv_cc = virtualenv.vars().get("CC")
        virtualenv_cxx = virtualenv.vars().get("CXX")
        
        cc = conf_cc or virtualenv_cc
        cxx = conf_cxx or virtualenv_cxx

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

        self._conanfile.output.info(f"Detected compiler executables: CC={cc}, CXX={cxx}")
        if cxx:
            cxx = cxx.replace("\\", "/")
        if cc:
            cc = cc.replace("\\", "/")
                
        return cc, cxx
    
    def _get_architecture(self):
        """Get B2 architecture from Conan settings"""
        if str(self._conanfile.settings.arch).startswith("x86"):
            return "x86"
        if str(self._conanfile.settings.arch).startswith("ppc"):
            return "power"
        if str(self._conanfile.settings.arch).startswith("arm"):
            return "arm"
        if str(self._conanfile.settings.arch).startswith("sparc"):
            return "sparc"
        if str(self._conanfile.settings.arch).startswith("mips64"):
            return "mips64"
        if str(self._conanfile.settings.arch).startswith("mips"):
            return "mips1"
        if str(self._conanfile.settings.arch).startswith("s390"):
            return "s390x"
        if str(self._conanfile.settings.arch).startswith("riscv"):
            return "riscv"
        
        return None    
    
    def _get_address_model(self):
        """Get B2 address-model from Conan settings"""
        if self._conanfile.settings.arch in ("x86_64", "ppc64", "ppc64le", "mips64",
                                  "armv8", "armv8.3", "sparcv9", "s390x", "riscv64",
                                  "wasm64"):
            return "64"
        return "32"

    def _create_library_config(self, dependency):
        self._conanfile.output.info(f"Dependency for B2: {dependency.ref.name}")
        aggregated_cpp_info = dependency.cpp_info.aggregated_components()
        if len(aggregated_cpp_info.libs) == 0:
            return ""

        name = self._get_b2_module_name(dependency)
        if not name:
            return ""

        includedir = aggregated_cpp_info.includedirs[0].replace("\\", "/")
        includedir = f"\"{includedir}\""
        libdir = aggregated_cpp_info.libdirs[0].replace("\\", "/")
        libdir = f"\"{libdir}\""
        lib = aggregated_cpp_info.libs[0]
        version = dependency.ref.version
        return f"\nusing {name} : {version} : " \
                f"<include>{includedir} " \
                f"<search>{libdir} " \
                f"<name>{lib} ;"
    
    def _generate_user_config(self):
        """Generate user-config.jam with toolset configuration"""
        toolset = self._get_toolset()
        toolset_version = self._get_toolset_version()
        _, cxx = self._get_compiler_executables()

        content = [f"# WARNING: Conan auto generated {self.USER_CONFIG} - DO NOT EDIT", ""]

        config_line = f"using {toolset}"
        if toolset_version:
            config_line += f" : {toolset_version}"
        if cxx and not is_msvc(self._conanfile):
            config_line += f" : {cxx}"
        config_line += " :"

        content.append(config_line)

        if is_apple_os(self._conanfile):
            apple_line = ""
            if self.settings.compiler == "apple-clang":
                apple_line += f" -isysroot {XCRun(self._conanfile).sdk_path}"
            if self.settings.get_safe("arch"):
                apple_line += f" -arch {to_apple_arch(self._conanfile)}"
            content.append(apple_line)

        if self._ar():
            ar_line = f'<archiver>"{self._ar()}" '
            content.append(ar_line)
        
        if self._ranlib():
            ranlib_line = f'<ranlib>"{self._ranlib()}" '
            content.append(ranlib_line)

        cxxflags = " ".join(self._conanfile.conf.get("tools.build:cxxflags", default=[], check_type=list)) + " "
        cflags = " ".join(self._conanfile.conf.get("tools.build:cflags", default=[], check_type=list)) + " "
        buildenv_vars = VirtualBuildEnv(self._conanfile).vars()
        cppflags = buildenv_vars.get("CPPFLAGS", "") + " "
        ldflags = " ".join(self._conanfile.conf.get("tools.build:sharedlinkflags", default=[], check_type=list)) + " "
        asflags = buildenv_vars.get("ASFLAGS", "") + " "

        sysroot = self._conanfile.conf.get("tools.build:sysroot")
        if sysroot and not is_msvc(self):
            sysroot = sysroot.replace("\\", "/")
            sysroot = f'"{sysroot}"' if ' ' in sysroot else sysroot
            cppflags += f"--sysroot={sysroot} "
            ldflags += f"--sysroot={sysroot} "

        flag_lines = []
        if cxxflags.strip():
            flag_lines.append(f'<cxxflags>"{cxxflags.strip()}" ')
        if cflags.strip():
            flag_lines.append(f'<cflags>"{cflags.strip()}" ')
        if cppflags.strip() or self._build_cross_flags():
            compiler_flags = cppflags.strip() + " "
            compiler_flags += " ".join(self._build_cross_flags())
            flag_lines.append(f'<compileflags>"{compiler_flags}" ')
        if ldflags.strip():
            flag_lines.append(f'<linkflags>"{ldflags.strip()}" ')
        if asflags.strip():
            flag_lines.append(f'<asmflags>"{asflags.strip()}" ')
        content.extend(flag_lines)

        if self._is_apple_embedded_platform():
            os_line = f'<target-os>"{self._b2_os()}" '
            content.append(os_line)

        content.append(" ;")

        user_config_jam = "\n".join(content)
        save(self._conanfile, self.USER_CONFIG, user_config_jam)
        
    def _generate_project_config(self):
        """Generate project-config.jam with Conan settings and dependencies"""
        content = [f"# WARNING: Conan auto generated {self.PROJECT_CONFIG} - DO NOT EDIT", ""]

        # Add build settings
        build_type = str(self._conanfile.settings.build_type).lower()
        content.append(f"# Build type: {build_type}")

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
        
        for require, dependency in self._conanfile.dependencies.items():
            if require.direct and not require.build and not require.test:
                content.append(self._create_library_config(dependency))

        content.append("")
        
        project_config_jam = "\n".join(content)
        save(self._conanfile, self.PROJECT_CONFIG, project_config_jam)

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
    url = "https://github.com/conan-io/conan-toolchains"
    homepage = "https://github.com/conan-io/conan-toolchains"
    description = "B2 (Boost.Build) toolchain generator for Conan"
    license = "MIT"
    topics = ("b2", "generator", "toolchain")
    package_type = "python-require"

    def package_info(self):
        self.generator_info = [B2Generator]