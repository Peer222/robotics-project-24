# type: ignore

import math
import os
import signal
import sys
import time

from PIL import Image
import cv2
import numpy as np
import torch
import unitree_legged_const as go2
from ultralytics import YOLO
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.go2.obstacles_avoid.obstacles_avoid_client import (
    ObstaclesAvoidClient,
)
from unitree_sdk2py.go2.sport.sport_client import (
    SportClient,
)
from unitree_sdk2py.go2.video.video_client import VideoClient
from unitree_sdk2py.idl.sensor_msgs.msg.dds_ import PointCloud2_
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_

from download import download_model
from obstacle_tracker import ObstacleTracker
# from training_code_isaacgym.environments import utils
# Download des MiDaS-Modell
download_model("https://github.com/intel-isl/MiDaS/releases/download/v2_1/model-f6b98070.pt", "depth_model.pt")

# from training_code_isaacgym.environments import utils

# Konfiguration
device = "cuda" if torch.cuda.is_available() else "cpu"
model_path = "./runs/detect/train/weights/best.pt"  # Pfad zum trainierten YOLO-Modell
depth_model_path = "./depth_model.pt"  # Pfad zum MiDaS-Modell
dataset_path = "./Data/Test/Test_plant.v1i.yolov11/test"  # Pfad zum Test-Datensatz
images_path = os.path.join(dataset_path, "images")

# Parameter
conf_threshold = 0.5
real_pot_width_cm = 20  # Breite des Topfes in cm
focal_length = 1200  # Beispielwert für die Kamerafokallänge (angepasst an die Kalibrierung)
focal_length_mask = 1200
image_center_x = 640  # Beispielwert für Bildmitte in Pixeln (angepasst an die Kameradaten)
field_of_view = 120  # Sichtfeld der Kamera in Grad

map_size = 1000

obstacle_avoid_client = None

viz_dev_images=False

# Handler-Methode: Signal für KeyboardInterrupt abfangen
def sigint_handler(signal, frame):
    """Keyboard Interrupt function."""
    print("--> KeyboardInterrupt abgefangen")
    global obstacle_avoid_client
    if obstacle_avoid_client is not None:
        obstacle_avoid_client.Move(0,0,0.0)
    # Programm abbrechen, sonst läuft loop weiter
    sys.exit(0)


def low_state_message_handler(msg: LowState_):
    """Get the low level states from the robot."""
    print("FR_0 motor state: ", msg.motor_state[go2.LegID["FR_0"]])
    print("IMU state: ", msg.imu_state)
    print("Battery state: voltage: ", msg.power_v, "current: ", msg.power_a)


def pointcloud_to_image(pointcloud_msg: PointCloud2_):
    # Dimensionen und Daten extrahieren
    width = pointcloud_msg.width
    point_step = pointcloud_msg.point_step
    data = np.array(pointcloud_msg.data, dtype=np.uint8)

    # Überprüfen, ob die Daten konsistent sind
    if len(data) % (width * point_step) != 0:
        raise ValueError("Datenlänge ist nicht mit der erwarteten Bildgröße kompatibel.")
    # Beispiel: Nur RGB-Daten extrahieren (angenommen, jeder Punkt hat 3 Bytes RGB)
    if point_step < 3:
        raise ValueError("Zu wenig Daten pro Punkt, um ein RGB-Bild zu erzeugen.")

    rgb_data = data[:width * point_step].reshape((width, point_step))
    # Extrahiere nur die ersten 3 Kanäle (RGB)
    image = rgb_data[:, :3].reshape((1, width, 3))  # Höhe ist 1

    # Optionale Umwandlung in 8-Bit-Format für Anzeige
    image = np.squeeze(image, axis=0)  # Höhe entfernen, da sie 1 ist
    return image


def lidar_cloud_message_handler(msg: PointCloud2_):
    """Get the point cloud states from the robot."""
    print("Width", msg.width, "Height", msg.height, "Len", len(msg.data))
    image = pointcloud_to_image(msg)
    cv2.imshow("Lidar", image)


def calculate_distance(pot_width_pixels, mask=False):
    """Berechnet die Entfernung anhand der Breite des Topfes in Pixeln."""
    if pot_width_pixels == 0:
        return -1
    if mask:
        return ((real_pot_width_cm * focal_length_mask) / pot_width_pixels)/100.0
    else:
        return ((real_pot_width_cm * focal_length) / pot_width_pixels)/100.0


def calculate_angle(x_center, image_width):
    """Berechnet den Winkel eines Objekts relativ zur Bildmitte."""
    relative_x = x_center - (image_width / 2)
    angle = (relative_x / image_width) * field_of_view / 180 * np.pi
    return -angle


def draw_grid(map_image, cell_size):
    """Zeichnet ein Schachbrettraster auf die Karte."""
    for x in range(0, map_size, cell_size):
        cv2.line(map_image, (x, 0), (x, map_size), (50, 50, 50), 1)  # Vertikale Linien
    for y in range(0, map_size, cell_size):
        cv2.line(map_image, (0, y), (map_size, y), (50, 50, 50), 1)  # Horizontale Linien


def update_local_map(robot_position, plants, pot_positions):
    """Aktualisiert die lokale Karte mit den Positionen des Roboters und der Pflanzen."""
    map_image = np.zeros((map_size, map_size, 3), dtype=np.uint8)

    cell_size = int(map_size / (map_size / 100))  # 1m Abstand in Pixel (angepasst an die Skalierung)
    draw_grid(map_image, cell_size)

    robot_x, robot_y = robot_position

    # Roboter zeichnen
    cv2.circle(map_image, (robot_x, robot_y), 10, (255, 0, 0), -1)  # Roboter als blauer Kreis

    # Pflanzen zeichnen
    for plant in plants:
        distance, angle = plant
        distance *= 100
        angle = angle / np.pi * 180
        angle += 90
        plant_x = int(robot_x + distance * math.cos(math.radians(angle)))
        plant_y = int(robot_y - distance * math.sin(math.radians(angle)))
        # plant_x = max(0,min(500,plant_x))
        # plant_y = max(0,min(500,plant_y))
        print("Plant distance: ", distance, " Angle: ", angle, "X: ", plant_x, " Y: ", plant_y)
        cv2.circle(map_image, (plant_x, plant_y), 5, (0, 255, 0), -1)  # Pflanzen als grüne Kreise

    # Töpfe zeichnen
    for pot in pot_positions:
        distance, angle = pot
        distance *= 100
        angle = angle / np.pi * 180
        angle += 90
        pot_x = int(robot_x + distance * math.cos(math.radians(angle)))
        pot_y = int(robot_y - distance * math.sin(math.radians(angle)))
        # pot_x = max(0,min(500,pot_x))
        # pot_y = max(0,min(500,pot_y))
        # print("Pot distance: ",distance, " Angle: ", angle, "X: ",pot_x," Y: ",pot_y)
        cv2.circle(map_image, (pot_x, pot_y), 5, (0, 0, 255), -1)  # Topf als roter Kreis

    cv2.imshow("Lokale Karte", map_image)


def main():  # noqa: D103
    signal.signal(signal.SIGINT, sigint_handler)
    # YOLO-Modell laden
    model = YOLO(model_path)
    # Tiefenmodell laden
    depth_model = ObstacleTracker(depth_model_path, device)
    print("Yolo loaded")
    # *********************
    from actor_critic import ActorCritic
    # def load_low_level_policy(sim_device):
    module = ActorCritic(  # Recurrent(
        num_actor_obs=3 + 12,  # * 2 + 6,
        num_critic_obs=3 + 12,  # * 2 + 6,
        num_actions=3,
        actor_hidden_dims=[512, 256, 128],  # 128, 128],
        critic_hidden_dims=[512, 256, 128],  # [128, 128],
    )
    # module = module.to(sim_device)
    import os
    # print("listdir", os.listdir("."))
    checkpoint = torch.load("models/single_plant_v3_2450.pt", map_location=torch.device("cpu"))
    print("checkpoint loaded")
    # print("low level policy", module)
    model_state_dict = checkpoint.get('model_state_dict')
    if model_state_dict is None:
        raise ValueError("The checkpoint does not contain a 'model_state_dict' key.")

    try:
        module.load_state_dict(model_state_dict)
    except RuntimeError as e:
        print("\nError while loading state dictionary:")
        print(e)
        # return None
    print("inference model loaded")

    # return module
    # *********************

    # Roboterposition (unten in der Mitte der Karte)
    robot_position = (int(map_size / 2), int(map_size) - 50)

    cv2.namedWindow("Erkannte_Objekte", cv2.WINDOW_AUTOSIZE)

    ChannelFactoryInitialize(0)
    """
    if len(sys.argv)>1:
        ChannelFactoryInitialize(0, "eno1") # Das hier ggf anpassen was im Networkmanager steht
    else:
        ChannelFactoryInitialize(0)
    """
    # urdf_loader = URDFLoader()
    global obstacle_avoid_client
    obstacle_avoid_client = ObstaclesAvoidClient()
    obstacle_avoid_client.SetTimeout(3.0)
    obstacle_avoid_client.Init()

    while not obstacle_avoid_client.SwitchGet()[1]:
        obstacle_avoid_client.SwitchSet(True)
        time.sleep(0.1)

    print("obstacles avoid switch on")
    obstacle_avoid_client.UseRemoteCommandFromApi(True)

    client = VideoClient()  # Create a video client
    client.SetTimeout(3.0)
    client.Init()

    sport_client = SportClient()
    sport_client.SetTimeout(10.0)
    sport_client.Init()

    code, data = client.GetImageSample()
    # lidar_subscriber
    # lidar_subscriber = ChannelSubscriber("rt/utlidar/cloud", PointCloud2_)
    # lidar_subscriber.Init(lidar_cloud_message_handler, 10)
    
    # lowstate_subscriber = ChannelSubscriber("rt/lowstate", LowState_)
    # lowstate_subscriber.Init(low_state_message_handler, 10)

    # prepare variables for the agent
    high_level_actions_prev1 = high_level_actions_prev2 = torch.zeros(3)

    # Alle Bilder im Ordner durchlaufen
    while code == 0:
        # Get Image data from Go2 robot
        code, data = client.GetImageSample()
        if data is not None:
            # Convert to numpy image
            image_data = np.frombuffer(bytes(data), dtype=np.uint8)
            image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
            depth = depth_model.estimate_depth(image=Image.fromarray(image))
            # Prediction durchführen
            results = model(image, verbose=False)
            plants = []
            pot_positions = []

            closest_pot = (float("inf"), None)

            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    _cls = int(box.cls[0].cpu().numpy())
                    confidence = box.conf[0].cpu().numpy()

                    if confidence > conf_threshold:

                        x_center = (x1 + x2) / 2
                        angle = calculate_angle(x_center, image.shape[1])

                        # Entfernungsschätzung für den Topf basierend auf der Bounding Box
                        if _cls == 1:  # Klasse 0 ist der Blumentopf (angepasst an die Klassendefinition)
                            cropped_image = image[int(y1):int(y2), int(x1):int(x2)]
                            gray = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)
                            threshold = 180  # Werte über 200 gelten als weiß

                            _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
                            if viz_dev_images:
                                cv2.imshow("Binary",binary)
                            height = binary.shape[0]
                            lower_third_start = int(height * (2 / 3))  # Start des unteren Drittels

                            white_pixel_positions = np.column_stack(np.where(binary[lower_third_start:, :] == 255))

                            pot_width_pixels = x2 - x1
                            if len(white_pixel_positions) > 0:
                                white_pixel_positions[:, 0] += lower_third_start

                                leftmost_pixel = white_pixel_positions[np.argmin(white_pixel_positions[:, 1])]

                                rightmost_pixel = white_pixel_positions[np.argmax(white_pixel_positions[:, 1])]
                                #print(f"Linkester weißer Pixel: {leftmost_pixel}")
                                #print(f"Rechtester weißer Pixel: {rightmost_pixel}")

                                cv2.circle(cropped_image, (leftmost_pixel[1], leftmost_pixel[0]), 5, (0, 0, 255), -1)  # Rot
                                cv2.circle(cropped_image, (rightmost_pixel[1], rightmost_pixel[0]), 5, (255, 0, 0), -1)  # Blau

                                pot_width_pixels = rightmost_pixel[1] - leftmost_pixel[1]
                                #print(pot_width_pixels, rightmost_pixel[1], leftmost_pixel[1])
                            if viz_dev_images:
                                cv2.imshow("Cropped Image",cropped_image)

                            distance = calculate_distance(pot_width_pixels, mask=True)

                            distance_non_mask = calculate_distance(x2-x1, mask=False)

                            if distance_non_mask < 1.5:
                                distance=distance_non_mask
                            if distance==-1:
                                continue
                            pot_positions.append((distance, angle))
                            if distance < closest_pot[0]:
                                closest_pot = [distance, angle]

                            if len(white_pixel_positions) > 0:
                                label = f"Class {int(_cls)}: {confidence:.2f}, Distance {(distance_non_mask)}, Mask-Distance:{(distance)}"
                            else:
                                label = f"Class {int(_cls)}: {confidence:.2f}, Distance {(distance_non_mask)}"
                       
                        else:
                            label = f"Class {int(_cls)}: {confidence:.2f}"
                        color = (0, 255, 0)  # Grün
                        cv2.rectangle(image, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                        cv2.putText(image, label, (int(x1), int(y1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            #print("inference step of policy")
            # Lokale Karte aktualisieren
            if viz_dev_images:
                update_local_map(robot_position, plants, pot_positions)
            # closest_pot
            print("Angle:",closest_pot[1],"Threshold",6 / 180 * np.pi,"Distance",closest_pot[0])
            if closest_pot[1] is not None and abs (closest_pot[1]) < 6 / 180 * np.pi and closest_pot[0] <= 0.8:
                print("Wait for standstill")
                obstacle_avoid_client.Move(0,0,0)
                time.sleep(3)
                print("Move slowly forward")
                obstacle_avoid_client.Move(0.2,0,0)
                print("STOP BECAUSE TOO CLOSE")
                time.sleep(2)
                print("Move towards plant")
                sport_client.Move(0.2,0,0)
                time.sleep(0.5)
                print("Wait for watering")
                obstacle_avoid_client.Move(0,0,0)
                time.sleep(10)
                print("Move back from plant")
                obstacle_avoid_client.Move(-0.2,0,0)
                time.sleep(2)
                obstacle_avoid_client.Move(0,0,0)
                break
            else:
                if closest_pot[1] is None:
                    object_detection_output = torch.tensor([0, 0, 0])
                else:
                    object_detection_output = torch.tensor(
                        [1.0, closest_pot[0]+0.4, closest_pot[1]])

                #print(f"{object_detection_output=}")

                #observable_depth_information = torch.ones(12)
                observable_depth_information = torch.tensor(depth)
                
                object_detection_output = object_detection_output
                observations = torch.cat([object_detection_output,
                                        observable_depth_information,  # torch.tanh(observable_depth_information),
                                        # high_level_actions_prev1,
                                        # high_level_actions_prev2
                                        ])

                commands = module.act_inference(observations.float())
                commands = torch.tanh(commands*0.1) * 0.2

                commands[2]*=5
                high_level_actions_prev2 = high_level_actions_prev1
                high_level_actions_prev1 = commands
                print("commands: " + str(commands[0]) + ", " + str(commands[1]) + ", " + str(commands[2]))

                code = obstacle_avoid_client.Move(commands[0].tolist(), commands[1].tolist(), commands[2].tolist())

                #print("Apply action", code)
                time.sleep(0.5)
                code = obstacle_avoid_client.Move(0, 0, 0)
                #print("Apply action", code)
                time.sleep(0.5)
            '''
            if closest_pot[1] is None:
                # sport_client.Move(0,0,0)# Hier ggf den Roboter drehen lassen bis er was erkennt
                code = obstacle_avoid_client.Move(0, 0, 0)
                print("NIX ERKANNT", code)

            else:
                print("Distance: ", closest_pot[0], "ANGLE: ", closest_pot[1])
                if abs(closest_pot[1]) < 20:
                    if closest_pot[0] > 60:  # cm
                        # sport_client.Move(1.0,0,0)
                        code = obstacle_avoid_client.Move(1.0, 0, 0)
                        print("MOVE FORWARD", code)
                    else:  # Hier ggf aufs Lidar wechseln
                        # sport_client.Move(0,0,0)
                        code = obstacle_avoid_client.Move(0, 0, 0)
                        print("STOP BECAUSE TOO CLOSE", code)
                else:
                    # Hier ggf links und rechts vertauscht
                    if closest_pot[1] < 0:  # Hier ggf den angle an steering mappen
                        # sport_client.Move(0,0,-1.0)
                        code = obstacle_avoid_client.Move(0, 0, -1.0)
                        print("TURN ROBOT RIGHT", code)
                    else:

                        print("TURN ROBOT LEFT", code)
            '''

            # Bild anzeigen
            cv2.imshow("Erkannte_Objekte", image)

            # Warten, bis eine Taste gedrückt wird
            cv2.waitKey(1)
            code = obstacle_avoid_client.Move(0., 0., 0.)
            #print("Apply action", code)
            cv2.waitKey(1)

    # OpenCV-Fenster schließen
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()