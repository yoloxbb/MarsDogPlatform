"""Installed Vision mock node, synthetic ROS image and task service; no devices."""
import argparse, hashlib, json, os, tempfile, time, uuid
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--install",type=Path,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    assert os.environ.get("ROS_LOCALHOST_ONLY")=="1"
    import rclpy, yaml
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.executors import SingleThreadedExecutor
    from sensor_msgs.msg import Image
    from std_msgs.msg import String
    from ament_index_python.packages import get_package_share_directory
    from marsdog_vision_interaction.nodes import vision_interaction_node as impl
    from marsdog_vision_interaction.srv import VisionTask
    module=Path(impl.__file__).resolve()
    assert module.is_relative_to(a.install.resolve())
    share=Path(get_package_share_directory("marsdog_vision_interaction"))
    assets={}
    for folder in ("config","launch","srv"):
        for f in (a.source/folder).rglob("*"):
            if not f.is_file() or "__pycache__" in f.parts: continue
            rel=f.relative_to(a.source)
            assert (share/rel).read_bytes()==f.read_bytes(), rel
            assets[str(rel)]=hashlib.sha256(f.read_bytes()).hexdigest()
    assert (share/"fastdds_env.sh").read_bytes()==(a.source/"scripts/fastdds_env.sh").read_bytes()
    prefix="/migration_vision_"+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(dir=a.output.parent,prefix="vision-data-") as directory:
        work=Path(directory)
        os.environ["MARSDOG_VISION_DATA_DIR"]=str(work/"data")
        config=yaml.safe_load((share/"config/vision.mock.yaml").read_text())
        assert config["face_api"]["enabled"] is False and config["depth_fusion"]["enabled"] is False
        assert all(v["type"]=="mock" for v in config["providers"].values())
        endpoints=[v for v in config["topics"].values() if isinstance(v,str) and v.startswith("/")]
        config_path=work/"vision.yaml"
        config_path.write_text(yaml.safe_dump(config))
        args=["--ros-args","-p","config_path:="+str(config_path),"-p","log_dir:="+str(work/"logs")]
        for e in endpoints:args+=["-r",e+":="+prefix+e]
        rclpy.init(args=args)
        executor=SingleThreadedExecutor()
        vision=client_node=None
        try:
            vision=impl.VisionInteractionNode()
            assert vision._vision_is_mock and vision._face_api is None
            assert vision._visual_pub.topic_name.startswith(prefix), vision._visual_pub.topic_name
            client_node=Node("vision_probe")
            events=[]
            client_node.create_subscription(String,"/perception/visual_event",lambda m:events.append(json.loads(m.data)),qos_profile_sensor_data)
            image_pub=client_node.create_publisher(Image,config["topics"]["camera_image"],10)
            client=client_node.create_client(VisionTask,"/perception/vision/task")
            executor.add_node(vision);executor.add_node(client_node)
            def until(predicate,seconds=10):
                end=time.monotonic()+seconds
                while not predicate() and time.monotonic()<end:executor.spin_once(timeout_sec=.05)
                assert predicate(),"Vision transport timeout"
            until(lambda:client.service_is_ready() and image_pub.get_subscription_count()==1)
            msg=Image(height=48,width=64,encoding="bgr8",step=192,data=bytes(48*192))
            msg.header.frame_id="mock_camera";msg.header.stamp=client_node.get_clock().now().to_msg()
            image_pub.publish(msg)
            until(lambda:bool(events))
            cases=[]
            for name,params,expected in [("check_person","{}",True),("query_targets","{}",True),
                ("get_object_detection_state","{}",True),("list_faces","{}",True),
                ("unsupported_migration_task","{}",False),("check_person","{",False)]:
                req=VisionTask.Request(task_id="probe",task_type=name,params_json=params)
                f=client.call_async(req);until(f.done)
                response=f.result()
                assert response.success is expected,(name,response.error_message)
                assert response.task_id=="probe" and response.task_type==name
                payload=json.loads(response.result_json) if response.result_json else {}
                cases.append({"task":name,"success":response.success,"keys":sorted(payload)})
            event=events[-1]
            assert event.get("vision_epoch")
            assert not event.get("active_target",{}).get("range_valid",False)
            result={"status":"PASS","module_file":str(module),"scope":"Installed mock provider + synthetic ROS image; no real camera/model/motion",
                "asset_hashes":assets,"service_cases":cases,"event_keys":sorted(event),
                "service_fields":{"request":VisionTask.Request.get_fields_and_field_types(),"response":VisionTask.Response.get_fields_and_field_types()},
                "endpoint_prefix":prefix}
            a.output.write_text(json.dumps(result,indent=2)+"\n")
            print(json.dumps({"status":"PASS","service_cases":len(cases)}))
        finally:
            executor.shutdown()
            if vision is not None:vision.destroy_node()
            if client_node is not None:client_node.destroy_node()
            rclpy.shutdown()

if __name__=="__main__":
    main()
