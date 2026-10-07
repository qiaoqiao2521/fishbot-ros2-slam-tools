cmake_minimum_required(VERSION 3.8)
project(fishbot_mujoco)
find_package(ament_cmake REQUIRED)
execute_process(COMMAND /usr/bin/python3
  ${CMAKE_CURRENT_SOURCE_DIR}/scripts/make_fixture_map.py
  ${CMAKE_CURRENT_SOURCE_DIR}/mjcf/arena.xml ${CMAKE_CURRENT_BINARY_DIR}/arena.pgm
  RESULT_VARIABLE fixture_result)
if(NOT fixture_result EQUAL 0)
  message(FATAL_ERROR "Synthetic map generation failed")
endif()
install(DIRECTORY launch config urdf mjcf DESTINATION share/${PROJECT_NAME}
  PATTERN "*.pgm" EXCLUDE)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/arena.pgm DESTINATION share/${PROJECT_NAME}/config)
install(DIRECTORY docs DESTINATION share/${PROJECT_NAME})
install(FILES README.md DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/verify_stack.py scripts/mission_bridge.py
  scripts/obstacle_controller.py scripts/wait_ready.py DESTINATION lib/${PROJECT_NAME})
ament_package()
