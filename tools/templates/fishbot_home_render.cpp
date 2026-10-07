// Native MuJoCo/EGL sight-line check. Static placement is not navigation evidence.
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <mujoco/mujoco.h>

#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using Model = std::unique_ptr<mjModel, decltype(&mj_deleteModel)>;
using Data = std::unique_ptr<mjData, decltype(&mj_deleteData)>;

void require(bool ok, const std::string &message) {
  if (!ok) throw std::runtime_error(message);
}

Model load(const fs::path &path) {
  std::array<char, 4096> error{};
  Model model(mj_loadXML(path.c_str(), nullptr, error.data(), error.size()), mj_deleteModel);
  require(bool(model), std::string("MuJoCo compile: ") + error.data());
  return model;
}

struct EGLContextOwner {
  EGLDisplay display = EGL_NO_DISPLAY;
  EGLContext context = EGL_NO_CONTEXT;
  EGLSurface surface = EGL_NO_SURFACE;
  EGLContextOwner() {
    display = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr);
    require(display != EGL_NO_DISPLAY && eglInitialize(display, nullptr, nullptr), "EGL initialize failed");
    require(eglBindAPI(EGL_OPENGL_API), "EGL OpenGL bind failed");
    const EGLint attributes[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RED_SIZE, 8,
      EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_DEPTH_SIZE, 24,
      EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE};
    EGLConfig config;
    EGLint count = 0;
    require(eglChooseConfig(display, attributes, &config, 1, &count) && count > 0, "EGL config failed");
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, nullptr);
    const EGLint size[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
    surface = eglCreatePbufferSurface(display, config, size);
    require(context != EGL_NO_CONTEXT && surface != EGL_NO_SURFACE &&
      eglMakeCurrent(display, surface, surface, context), "EGL context failed");
  }
  ~EGLContextOwner() {
    if (display != EGL_NO_DISPLAY) {
      eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
      if (surface != EGL_NO_SURFACE) eglDestroySurface(display, surface);
      if (context != EGL_NO_CONTEXT) eglDestroyContext(display, context);
      eglTerminate(display);
    }
  }
};


// Offline renderer only. Views file lines: name x y yaw. Never starts ROS.
int main(int argc, char **argv) try {
  require(argc == 4, "Expected SCENE_XML VIEWS_TXT OUTPUT_DIR");
  auto model = load(argv[1]);
  Data data(mj_makeData(model.get()), mj_deleteData);
  const fs::path output(argv[3]); fs::create_directories(output);
  const int id = mj_name2id(model.get(), mjOBJ_CAMERA, "inspection_camera");
  const int joint = mj_name2id(model.get(), mjOBJ_JOINT, "base_free_joint");
  require(id >= 0 && joint >= 0, "Missing camera or robot base joint");
  const int width = model->cam_resolution[2*id], height = model->cam_resolution[2*id+1];
  const int qadr = model->jnt_qposadr[joint];
  EGLContextOwner egl; mjvScene scene{}; mjrContext context{}; mjvOption option; mjvCamera camera;
  mjv_defaultOption(&option); option.flags[mjVIS_RANGEFINDER] = 0;
  for (auto &group : option.sitegroup) group = 0;
  mjv_defaultCamera(&camera); camera.type = mjCAMERA_FIXED; camera.fixedcamid = id;
  mjv_defaultScene(&scene); mjr_defaultContext(&context);
  mjv_makeScene(model.get(), &scene, std::max(2000, static_cast<int>(2*model->ngeom)));
  mjr_makeContext(model.get(), &context, mjFONTSCALE_150);
  mjr_resizeOffscreen(width, height, &context); mjr_setBuffer(mjFB_OFFSCREEN, &context);
  std::vector<unsigned char> rgb(width*height*3);
  std::ifstream views(argv[2]); require(views.good(), "Missing view file");
  std::string name; double x, y, yaw; int count = 0;
  while (views >> name >> x >> y >> yaw) {
    require(name.find('/') == std::string::npos && name.find("..") == std::string::npos, "Unsafe image name");
    require(std::isfinite(x) && std::isfinite(y) && std::isfinite(yaw), "Nonfinite view pose");
    mj_resetData(model.get(), data.get());
    data->qpos[qadr] = x; data->qpos[qadr+1] = y;
    data->qpos[qadr+3] = std::cos(yaw/2); data->qpos[qadr+4] = 0;
    data->qpos[qadr+5] = 0; data->qpos[qadr+6] = std::sin(yaw/2);
    mj_forward(model.get(), data.get());
    mjv_updateScene(model.get(), data.get(), &option, nullptr, &camera, mjCAT_ALL, &scene);
    const mjrRect viewport{0, 0, width, height}; mjr_render(viewport, &scene, &context);
    mjr_readPixels(rgb.data(), nullptr, viewport, &context);
    std::ofstream stream(output/(name+".ppm"), std::ios::binary);
    stream << "P6\n" << width << ' ' << height << "\n255\n";
    for (int row = height-1; row >= 0; --row)
      stream.write(reinterpret_cast<char *>(rgb.data()+3*row*width), 3*width);
    require(stream.good(), "Image write failed"); ++count;
  }
  require(views.eof() && count > 0, "Malformed or empty view file");
  std::cout << "Native static RGB render passed: " << count << " views, " << model->ngeom << " geoms.\n";
  mjr_freeContext(&context); mjv_freeScene(&scene); return 0;
} catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
