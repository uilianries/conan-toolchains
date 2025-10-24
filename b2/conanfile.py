import re
import shutil
from conan import ConanFile
from conan.tools.files import save
from conan.tools.microsoft import is_msvc, MSBuildToolchain, is_msvc_static_runtime, msvc_runtime_flag
from conan.tools.apple import is_apple_os, XCRun, to_apple_arch
from conan.tools.scm import Version
from conan.tools.env import VirtualBuildEnv
from conan.tools.build import cross_building, cppstd_flag
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
        self._features = {}
        self._variables = {}

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

    def _get_cppstd(self):
        cppstd_version = cppstd_flag(self._conanfile)
        has_gnu = "gnu" in cppstd_version
        if cppstd_version[-2:].isdigit():
            # expected -std=c++11 or /std:c++11
            cppstd_version = cppstd_version[-2:]
        elif cppstd_version.endswith("latest"):
            # expected -std=c++latest or /std:c++latest
            cppstd_version = "latest"
        else:
            # most probably is 1z, 2a ...
            cppstd_version = cppstd_version[-2:]

        if has_gnu:
            return "gnu", cppstd_version

        return None, cppstd_version

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

    def _get_os(self):
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
            return "msvc"
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

        if not cxx:
            compiler_version = Version(self._conanfile.settings.compiler.version)
            major = compiler_version.major
            if is_apple_os(self._conanfile) and self._conanfile.settings.compiler == "apple-clang":
                cxx = XCRun(self._conanfile).cxx
            elif self._conanfile.settings.compiler == "gcc":
                cxx = shutil.which(f"g++-{compiler_version}") or shutil.which(f"g++-{major}") or shutil.which("g++") or ""
            elif self._conanfile.settings.compiler == "clang":
                cxx = shutil.which(f"clang++-{compiler_version}") or shutil.which(f"clang++-{major}") or shutil.which("clang++") or ""
            elif self._conanfile.settings.compiler == "msvc":
                # MSVC is auto-detected by B2
                return None, None
        if cxx:
            cxx = cxx.replace("\\", "/")
        if cc:
            cc = cc.replace("\\", "/")

        self._conanfile.output.info(f"Detected compiler executables: CC={cc}, CXX={cxx}")
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

        if is_apple_os(self._conanfile):
            apple_line = ""
            if self._conanfile.settings.compiler == "apple-clang":
                apple_line += f" -isysroot {XCRun(self._conanfile).sdk_path}"
            if self._conanfile.settings.get_safe("arch"):
                apple_line += f" -arch {to_apple_arch(self._conanfile)}"
            config_line += f" {apple_line.strip()}"

        config_line += " ;"

        content.append(config_line)

        content.append("project")
        content.append("    : requirements")

        toolset_full = f"{toolset}-{toolset_version}" if toolset_version else toolset
        self.set_feature("toolset", toolset_full)

        dialect, cppstd = self._get_cppstd()
        if dialect:
            self.set_feature("cxxstd-dialect", dialect)
        self.set_feature("cxxstd", cppstd)

        if self._ar():
            self.set_feature("archiver", self._ar())

        if self._ranlib():
            ranlib_line = f'<ranlib>"{self._ranlib()}" '
            content.append(ranlib_line)

        cxxflags = self._conanfile.conf.get("tools.build:cxxflags", default=[], check_type=list)
        cflags = self._conanfile.conf.get("tools.build:cflags", default=[], check_type=list)
        defines = self._conanfile.conf.get("tools.build:defines", default=[], check_type=list)
        buildenv_vars = VirtualBuildEnv(self._conanfile).vars()
        cppflags = buildenv_vars.get("CPPFLAGS", "").split(" ")
        ldflags = self._conanfile.conf.get("tools.build:sharedlinkflags", default=[], check_type=list)
        asflags = buildenv_vars.get("ASFLAGS", "").split(" ")

        sysroot = self._conanfile.conf.get("tools.build:sysroot")
        if sysroot and not is_msvc(self):
            sysroot = sysroot.replace("\\", "/")
            sysroot = f'"{sysroot}"' if ' ' in sysroot else sysroot
            cppflags.append(f"--sysroot={sysroot} ")
            ldflags.append(f"--sysroot={sysroot} ")

        if cppflags or self._build_cross_flags():
            compiler_flags = cppflags or []
            compiler_flags.extend(self._build_cross_flags())
            for it in compiler_flags:
                self.set_feature("compileflags", it)
        if asflags:
            self.set_feature("asmflags", asflags)
        if cxxflags:
            self.set_feature("cxxflags", cxxflags)
        if cflags:
            self.set_feature("cflags", cflags)
        if ldflags:
            self.set_feature("linkflags", ldflags)
        if defines:
            self.set_feature("define", defines)

        if self._conanfile.options.get_safe("shared"):
            self.set_feature("link", "shared")
        else:
            self.set_feature("link", "static")
        if self._conanfile.options.get_safe("fPIC"):
            self.set_feature("cxxflags", "-fPIC")

        if self._conanfile.settings.build_type == "Debug":
            self.set_feature("variant", "debug")
        else:
            self.set_feature("variant", "release")

        arch = self._get_architecture()
        if arch:
            self.set_feature("architecture", arch)

        address_model = self._get_address_model()
        if address_model:
            self.set_feature("address-model", address_model)

        if is_msvc(self._conanfile):
            self.set_feature("runtime-link", "static" if is_msvc_static_runtime(self) else "shared")
            self.set_feature("runtime-debugging", "on" if "d" in msvc_runtime_flag(self) else "off")

        #target_os = self._get_os()
        #if target_os:
        #    self.set_feature("target-os", target_os)

        for name, value in self._features.items():
            if isinstance(value, list):
                for it in value:
                    content.append(f'      <{name}>{it}')
            else:
                content.append(f'      <{name}>{value}')

        content.append("   ;")

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

        # Add variables
        content.append("# Conan variables")
        for variable, value in self._variables.items():
            content.append(f"{variable} = {value} ;")

        # Add dependency information
        content.append("# Conan dependencies")

        for require, dependency in self._conanfile.dependencies.items():
            if require.direct and not require.build and not require.test:
                content.append(self._create_library_config(dependency))

        content.append("")

        project_config_jam = "\n".join(content)
        save(self._conanfile, self.PROJECT_CONFIG, project_config_jam)


    def set_feature(self, name, value):
        # https://www.bfgroup.xyz/b2/tutorial.html#_feature_reference
        valid_features = ["address-model", "architecture", "c++-template-depth", "cflags",
                          "cxxstd", "cxxstd-dialect", "compileflags", "asmflags",
                          "cxxflags", "debug-symbols", "def-file", "define", "embed-manifest",
                          "host-os", "include", "inlining", "library", "link", "linkflags",
                          "location", "name", "optimization", "profiling", "runtime-link",
                          "search", "source", "target-os", "threading", "toolset", "undef",
                          "use", "variant", "visibility", "warnings", "warnings-as-errors"]
        if name not in valid_features:
            raise ConanException(f"B2Generator: Invalid feature '{name}'. See https://www.bfgroup.xyz/b2/tutorial.html#_feature_reference")
        if isinstance(value, list):
            value = [v for v in value if v]
            if not value:
                self._conanfile.output.debug(f"B2Generator: Ignoring empty feature list for '{name}'")
                return
        self._features[name] = value


    def add_dependency(self, name, version=None, executable=None, include_dir=None, lib_dir=None, lib_name=None):
        """Add a dependency to be included in the generated project-config.jam"""
        dep_config = f"using {name}"
        if version:
            dep_config += f" : {version}"
        if executable:
            executable = executable.replace("\\", "/")
            dep_config += f" : \"{executable}\""
        if include_dir:
            include_dir = include_dir.replace("\\", "/")
            dep_config += f" <include>\"{include_dir}\""
        if lib_dir:
            lib_dir = lib_dir.replace("\\", "/")
            dep_config += f" <search>\"{lib_dir}\""
        if lib_name:
            dep_config += f" <name>{lib_name}"
        dep_config += " ;"


    def set_variable(self, variable, value):
        """Set a variable in the generated project-config.jam"""
        self._variables[variable] = value

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