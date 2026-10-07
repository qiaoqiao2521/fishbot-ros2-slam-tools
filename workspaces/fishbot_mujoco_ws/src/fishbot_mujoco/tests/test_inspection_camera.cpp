// Native MuJoCo/EGL fixture test. It starts no ROS nodes and sends no commands.
// Static qpos placement tests sight lines only; it is not navigation evidence.
// Usage: test_inspection_camera PACKAGE_DIR EXTERNAL_OUTPUT_DIR
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

struct Counts { int blue = 0, green = 0, red = 0; };

int main(int argc, char **argv) try {
  require(argc == 3, "Expected PACKAGE_DIR and EXTERNAL_OUTPUT_DIR");
  const fs::path package(argv[1]), output(argv[2]);
  fs::create_directories(output);
  const auto original = load(package / "mjcf/fishbot.xml");
  const auto variant = load(package / "mjcf/fishbot_inspection.xml");
  require(original->nq == variant->nq && original->nv == variant->nv &&
    original->nu == variant->nu && original->nbody == variant->nbody &&
    original->ngeom == variant->ngeom && original->nsensor == variant->nsensor,
    "Camera variant changed physical model topology");
  for (int i = 0; i < original->nbody; ++i) {
    require(original->body_mass[i] == variant->body_mass[i], "Camera variant changed body mass");
    for (int j = 0; j < 3; ++j)
      require(original->body_inertia[3*i+j] == variant->body_inertia[3*i+j], "Camera variant changed inertia");
  }
  for (int i = 0; i < original->ngeom; ++i) {
    require(original->geom_contype[i] == variant->geom_contype[i] &&
      original->geom_conaffinity[i] == variant->geom_conaffinity[i], "Camera variant changed contact masks");
    for (int j = 0; j < 3; ++j)
      require(original->geom_size[3*i+j] == variant->geom_size[3*i+j], "Camera variant changed geometry");
  }
  auto model = load(package / "mjcf/inspection.xml");
  Data data(mj_makeData(model.get()), mj_deleteData);
  const int camera_id = mj_name2id(model.get(), mjOBJ_CAMERA, "inspection_camera");
  const int base_joint = mj_name2id(model.get(), mjOBJ_JOINT, "base_free_joint");
  const int base_body = mj_name2id(model.get(), mjOBJ_BODY, "base_link");
  require(camera_id >= 0 && base_joint >= 0 && base_body >= 0, "Missing robot camera or joint");
  require(model->cam_bodyid[camera_id] == base_body, "Camera is not robot-mounted");
  const int width = model->cam_resolution[2*camera_id], height = model->cam_resolution[2*camera_id+1];
  require(width == 640 && height == 480, "Unexpected camera resolution");
  const int qadr = model->jnt_qposadr[base_joint];

  EGLContextOwner egl;
  mjvScene scene{};
  mjrContext context{};
  mjvOption option;
  mjvCamera camera;
  mjv_defaultOption(&option);
  option.flags[mjVIS_RANGEFINDER] = 0;
  for (auto &group : option.sitegroup) group = 0;
  mjv_defaultCamera(&camera);
  camera.type = mjCAMERA_FIXED;
  camera.fixedcamid = camera_id;
  mjv_defaultScene(&scene);
  mjr_defaultContext(&context);
  mjv_makeScene(model.get(), &scene, 2000);
  mjr_makeContext(model.get(), &context, mjFONTSCALE_150);
  mjr_resizeOffscreen(width, height, &context);
  mjr_setBuffer(mjFB_OFFSCREEN, &context);
  std::vector<unsigned char> rgb(width*height*3);

  auto render = [&](double x, double y, double yaw, const std::string &file) {
    mj_resetData(model.get(), data.get());
    data->qpos[qadr] = x; data->qpos[qadr+1] = y;
    data->qpos[qadr+3] = std::cos(yaw/2); data->qpos[qadr+4] = 0;
    data->qpos[qadr+5] = 0; data->qpos[qadr+6] = std::sin(yaw/2);
    mj_forward(model.get(), data.get());
    mjv_updateScene(model.get(), data.get(), &option, nullptr, &camera, mjCAT_ALL, &scene);
    const mjrRect viewport{0, 0, width, height};
    mjr_render(viewport, &scene, &context);
    mjr_readPixels(rgb.data(), nullptr, viewport, &context);
    Counts count;
    // Count only the central image; neighboring stations cannot establish visibility.
    for (int row = height/4; row < 3*height/4; ++row) {
      for (int col = width/4; col < 3*width/4; ++col) {
        const int offset = 3*(row*width+col);
        const int r = rgb[offset], g = rgb[offset+1], b = rgb[offset+2];
        count.blue += b > 100 && b > 1.7*r && b > 1.7*g;
        count.green += g > 100 && g > 1.7*r && g > 1.7*b;
        count.red += r > 100 && r > 1.7*g && r > 1.7*b;
      }
    }
    if (!file.empty()) {
      std::ofstream stream(output / file, std::ios::binary);
      stream << "P6\n" << width << ' ' << height << "\n255\n";
      for (int row = height-1; row >= 0; --row)
        stream.write(reinterpret_cast<char *>(rgb.data()+3*row*width), 3*width);
      require(stream.good(), "Image write failed");
    }
    return count;
  };
  std::cout << "{\"scope\":\"native_static_camera_fixture_only\",\"stations\":[";
  for (int station = 0; station < 3; ++station) {
    Counts nominal;
    for (int perturbation = -1; perturbation <= 1; ++perturbation) {
      const auto count = render(.5+station+.03*perturbation, .3+.03*perturbation,
        M_PI/2+.09*perturbation,
        perturbation == 0 ? "station_"+std::to_string(station+1)+".ppm" : "");
      require(count.blue > 1000, "Blue frame not visible at goal tolerance");
      require(station == 0 ? count.green > 500 && count.red < 50 :
        station == 1 ? count.red > 500 && count.green < 50 : count.red < 50 && count.green < 50,
        "Rendered lamp differs from fixture expectation");
      if (perturbation == 0) nominal = count;
    }
    if (station) std::cout << ',';
    std::cout << "{\"station\":" << station+1 << ",\"blue_pixels\":" << nominal.blue
      << ",\"green_pixels\":" << nominal.green << ",\"red_pixels\":" << nominal.red << '}';
  }
  const auto away = render(.5, .3, -M_PI/2, "away.ppm");
  require(away.blue < 50 && away.red < 50 && away.green < 50, "Away-facing camera should not see a station");
  std::cout << "],\"goal_tolerance_views\":9,\"away_view\":\"no_marker\",\"result\":\"pass\"}\n";
  mjr_freeContext(&context);
  mjv_freeScene(&scene);
  return 0;
} catch (const std::exception &error) {
  std::cerr << error.what() << '\n';
  return 1;
}
