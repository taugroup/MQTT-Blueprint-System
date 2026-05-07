##	How to use the Sub:Sen Parser Instructions String in the APB_MQTT_Client:
##	
##	Say you have a list that looks like this =
##
##	Subsystem A:Sensor A,Sensor B,Sensor C,Sensor D;
##	Subsystem B:Sensor E,Sensor F,Sensor G,Sensor H;
##	Subsystem C:Sensor I,Sensor J,Sensor K,Sensor L;
##	Subsystem D:Sensor A,Sensor B,Sensor C,Sensor D,Sensor M,Sensor N,Sensor O,Sensor P;
##	
##	The final string you copy & paste would look like this (No spaces, unless it is in the name) = 
##	Subsystem A:Sensor A,Sensor B,Sensor C,Sensor D;Subsystem B:Sensor E,Sensor F,Sensor G,Sensor H;Subsystem C:Sensor I,Sensor J,Sensor K,Sensor L;Subsystem D:Sensor A,Sensor B,Sensor C,Sensor D,Sensor M,Sensor N,Sensor O,Sensor P;
##	
##	This defines what "Subsystem" means and what sensors to attach to the Subsystem
##	So "Subsystem A:Sensor A,Sensor B, Sensor C, Sensor D;" 
##	Means Subsystem A contains everything to the right of ":" which is Sensors A-D and the ";" indicates the end of that Subsystems components
##	
##	
##	
##	How to use the Unit:Sen Parser Instructions in the APB_MQTT_Client:
##	
##	Say you have a list of units that looks like this =
##	
##	Units A:Sensor A,Sensor B,Sensor M;
##	Units B:Sensor C,Sensor F,Sensor L,Sensor N;
##	Units C:Sensor E,Sensor G,Sensor K,Sensor O;
##	Units D:Sensor D,Sensor H,Sensor J,Sensor P;
##	Units E:Sensor I;
##	
##	The final string you copy & paste would look like this (No spaces, unless it is in the name) = 
##	Units A:Sensor A,Sensor B,Sensor M;Units B:Sensor C,Sensor F,Sensor L,Sensor N;Units C:Sensor E,Sensor G,Sensor K,Sensor O;Units D:Sensor D,Sensor H,Sensor J,Sensor P;Units E:Sensor I;
##	
##	Like the Sub:Sen Parser, the Unit:Sen Parser is not tied to the subsystem, instead the units are associated with any number of sensors (Just don't make the same sensor have another unit)


