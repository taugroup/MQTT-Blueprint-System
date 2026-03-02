	DEPENDANCIES

	Requirements:
		This plugin requires "MQTT_Utilities" make sure this plugin is enabled before using



	SETUP

	How to use:
		1.) Edit "controlPanel.txt" to map the correct paths to the specified variables
		2.) [This step is only required for first time setup or New Unreal Engine Version]
			Run "runEmbed.bat" to build the plugin for your Unreal Engine
		3.) Run "runEnable.bat" to enable the plugin and its contents to your UE Project
			Once Build successful:
				In your UE Project, in the content browser go to-
					Engine>Plugin>MQTT_blueprint_system Content
						Migrate the "MQTT" folder to your current project
		4.) Place MQTT_Client in level to create the MQTT_Client
		5.) Place MQTT_Import_Data in level to communicate/rig functionality of MQTT
			Once placed:
				In MQTT_Client details panel>Place MQTT_Import_Data to its required field
		6.) Navigate to YourProjectPath>MQTT_Python Folder
			This is the folder to test data on localHost
		7.) Navigate to YourProjectPath>MQTT_BP Guide Folder
			This is the folder for additional help



	TROUBLESHOOTING

	If you do not see "MQTT_Data_Import" in details panel:
		Place MQTT_Import_Data in level to communicate/rig functionality of MQTT


	If you get "Warning":

		This plugin requires "MQTT_Utilities" make sure this plugin is enabled before using
	

	If you get "Blueprint Compile Error":

		1.) This plugin requires "MQTT_Utilities" make sure this plugin is enabled before using
		2.) Remove the blueprint from level and delete the MQTT folder in your projects content folder
			After you enable MQTT_Utilities:
				Migrate the MQTT folder from your Engine>Plugins>MQTT_blueprint_system Content Folder

	If you do not see "MQTT_Python" or "MQTT_BP Guide" Folders:
		Run "runEnable.bat" to enable the plugin and its contents to your UE Project
		
