typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef signed int s32;
typedef signed short s16;
typedef unsigned long u64;
typedef signed long s64;
typedef unsigned long metal_phys_addr_t;

typedef void (*XRFdc_StatusHandler)(void *CallBackRef, u32 Type, u32 Tile_Id, u32 Block_Id, u32 StatusEvent);

/**
 * PLL settings.
 */
typedef struct {
	u32 Enabled; /* PLL Enables status (not a setter) */
	double RefClkFreq;
	double SampleRate;
	u32 RefClkDivider;
	u32 FeedbackDivider;
	u32 OutputDivider;
	u32 FractionalMode; /* Fractional mode is currently not supported */
	u64 FractionalData; /* Fractional data is currently not supported */
	u32 FractWidth; /* Fractional width is currently not supported */
} XRFdc_PLL_Settings;
/**
* ClkIntraTile Settings.
*/
typedef struct {
	u8 SourceType;
	u8 SourceTile;
	u32 PLLEnable;
	double RefClkFreq;
	double SampleRate;
	u8 DivisionFactor;
	u8 DistributedClock;
	u8 Delay;
} XRFdc_Tile_Clock_Settings;
/**
* Clk Distribution Settings.
*/
typedef struct {
	u8 MaxDelay;
	u8 MinDelay;
	u8 IsDelayBalanced;
	u8 Source;
	u8 UpperBound;
	u8 LowerBound;
	XRFdc_Tile_Clock_Settings ClkSettings[2][4]; /*[Type][Tile] e.g. ClkSettings[XRFDC_ADC_TILE][1] for ADC1*/
} XRFdc_Distribution_Info;

typedef struct {
	u32 SourceType;
	u32 SourceTileId;
	u32 EdgeTileIds[2];
	u32 EdgeTypes[2];
	double DistRefClkFreq;
	u32 DistributedClock;
	double SampleRates[2][4]; /*[Type][Tile] e.g. ClkSettings[XRFDC_ADC_TILE][1] for ADC1*/
	u32 ShutdownMode;
	XRFdc_Distribution_Info Info;
} XRFdc_Distribution_Settings;
typedef struct {
	XRFdc_Distribution_Settings Distributions[8];
} XRFdc_Distribution_System_Settings;

/**
 * MTS DTC Settings.
 */
typedef struct {
	u32 RefTile;
	u32 IsPLL;
	int Target[4];
	int Scan_Mode;
	int DTC_Code[4];
	int Num_Windows[4];
	int Max_Gap[4];
	int Min_Gap[4];
	int Max_Overlap[4];
} XRFdc_MTS_DTC_Settings;

/**
 * MTS Sync Settings.
 */
typedef struct {
	u32 RefTile;
	u32 Tiles;
	int Target_Latency;
	int Offset[4];
	int Latency[4];
	int Marker_Delay;
	int SysRef_Enable;
	XRFdc_MTS_DTC_Settings DTC_Set_PLL;
	XRFdc_MTS_DTC_Settings DTC_Set_T1;
} XRFdc_MultiConverter_Sync_Config;

/**
 * MTS Marker Struct.
 */
typedef struct {
	u32 Count[4];
	u32 Loc[4];
} XRFdc_MTS_Marker;

/**
 * ADC Signal Detect Settings.
 */
typedef struct {
	u8 Mode;
	u8 TimeConstant;
	u8 Flush;
	u8 EnableIntegrator;
	u16 Threshold;
	u16 ThreshOnTriggerCnt; /* the number of times value must exceed Threshold before turning on*/
	u16 ThreshOffTriggerCnt; /* the number of times value must be less than Threshold before turning off*/
	u8 HysteresisEnable;
} XRFdc_Signal_Detector_Settings;
/**
 * QMC settings.
 */
typedef struct {
	u32 EnablePhase;
	u32 EnableGain;
	double GainCorrectionFactor;
	double PhaseCorrectionFactor;
	s32 OffsetCorrectionFactor;
	u32 EventSource;
} XRFdc_QMC_Settings;

/**
 * Coarse delay settings.
 */
typedef struct {
	u32 CoarseDelay;
	u32 EventSource;
} XRFdc_CoarseDelay_Settings;

/**
 * Mixer settings.
 */
typedef struct {
	double Freq;
	double PhaseOffset;
	u32 EventSource;
	u32 CoarseMixFreq;
	u32 MixerMode;
	u8 FineMixerScale; /* NCO output scale, valid values 0,1 and 2 */
	u8 MixerType;
} XRFdc_Mixer_Settings;

/**
 * ADC block Threshold settings.
 */
typedef struct {
	u32 UpdateThreshold; /* Selects which threshold to update */
	u32 ThresholdMode[2]; /* Entry 0 for Threshold0 and 1 for Threshold1 */
	u32 ThresholdAvgVal[2]; /* Entry 0 for Threshold0 and 1 for Threshold1 */
	u32 ThresholdUnderVal[2]; /* Entry 0 for Threshold0 and 1 for Threshold1 */
	u32 ThresholdOverVal[2]; /* Entry 0 is for Threshold0 and 1 for Threshold1 */
} XRFdc_Threshold_Settings;

/**
 * RFSoC Calibration coefficients generic struct
 */
typedef struct {
	u32 Coeff0;
	u32 Coeff1;
	u32 Coeff2;
	u32 Coeff3;
	u32 Coeff4;
	u32 Coeff5;
	u32 Coeff6;
	u32 Coeff7;
} XRFdc_Calibration_Coefficients;

/**
 * RFSoC Power Mode settings
 */
typedef struct {
	u32 DisableIPControl; /*Disables IP RTS control of the power mode*/
	u32 PwrMode; /*The power mode*/
} XRFdc_Pwr_Mode_Settings;

/**
 * RFSoC DSA settings
 */
typedef struct {
	u32 DisableRTS; /*Disables RTS control of DSA attenuation*/
	float Attenuation; /*Attenuation*/
} XRFdc_DSA_Settings;

/**
 * RFSoC Calibration freeze settings struct
 */
typedef struct {
	u32 CalFrozen; /*Status indicates calibration freeze state*/
	u32 DisableFreezePin; /*Disable the calibration freeze pin*/
	u32 FreezeCalibration; /*Setter for freezing*/
} XRFdc_Cal_Freeze_Settings;

/**
 * RFSoC Tile status.
 */
typedef struct {
	u32 IsEnabled; /* 1, if tile is enabled, 0 otherwise */
	u32 TileState; /* Indicates Tile Current State */
	u8 BlockStatusMask; /* Bit mask for block status, 1 indicates block enable */
	u32 PowerUpState;
	u32 PLLState;
} XRFdc_TileStatus;

/**
 * RFSoC Data converter IP status.
 */
typedef struct {
	XRFdc_TileStatus DACTileStatus[4];
	XRFdc_TileStatus ADCTileStatus[4];
	u32 State;
} XRFdc_IPStatus;

/**
 * status of DAC or ADC blocks in the RFSoC Data converter.
 */
typedef struct {
	double SamplingFreq;
	u32 AnalogDataPathStatus;
	u32 DigitalDataPathStatus;
	u8 DataPathClocksStatus; /* Indicates all required datapath
				clocks are enabled or not, 1 if all clocks enabled, 0 otherwise */
	u8 IsFIFOFlagsEnabled; /* Indicates FIFO flags enabled or not,
				 1 if all flags enabled, 0 otherwise */
	u8 IsFIFOFlagsAsserted; /* Indicates FIFO flags asserted or not,
				 1 if all flags asserted, 0 otherwise */
} XRFdc_BlockStatus;

/**
 * DAC block Analog DataPath Config settings.
 */
typedef struct {
	u32 BlockAvailable;
	u32 InvSyncEnable;
	u32 MixMode;
	u32 DecoderMode;
} XRFdc_DACBlock_AnalogDataPath_Config;

/**
 * DAC block Digital DataPath Config settings.
 */
typedef struct {
	u32 MixerInputDataType;
	u32 DataWidth;
	u32 InterpolationMode;
	u32 FifoEnable;
	u32 AdderEnable;
	u32 MixerType;
	double NCOFreq;
} XRFdc_DACBlock_DigitalDataPath_Config;

/**
 * ADC block Analog DataPath Config settings.
 */
typedef struct {
	u32 BlockAvailable;
	u32 MixMode;
} XRFdc_ADCBlock_AnalogDataPath_Config;

/**
 * DAC block Digital DataPath Config settings.
 */
typedef struct {
	u32 MixerInputDataType;
	u32 DataWidth;
	u32 DecimationMode;
	u32 FifoEnable;
	u32 MixerType;
	double NCOFreq;
} XRFdc_ADCBlock_DigitalDataPath_Config;

/**
 * DAC Tile Config structure.
 */
typedef struct {
	u32 Enable;
	u32 PLLEnable;
	double SamplingRate;
	double RefClkFreq;
	double FabClkFreq;
	u32 FeedbackDiv;
	u32 OutputDiv;
	u32 RefClkDiv;
	u32 MultibandConfig;
	double MaxSampleRate;
	u32 NumSlices;
	u32 LinkCoupling;
	XRFdc_DACBlock_AnalogDataPath_Config DACBlock_Analog_Config[4];
	XRFdc_DACBlock_DigitalDataPath_Config DACBlock_Digital_Config[4];
} XRFdc_DACTile_Config;

/**
 * ADC Tile Config Structure.
 */
typedef struct {
	u32 Enable; /* Tile Enable status */
	u32 PLLEnable; /* PLL enable Status */
	double SamplingRate;
	double RefClkFreq;
	double FabClkFreq;
	u32 FeedbackDiv;
	u32 OutputDiv;
	u32 RefClkDiv;
	u32 MultibandConfig;
	double MaxSampleRate;
	u32 NumSlices;
	XRFdc_ADCBlock_AnalogDataPath_Config ADCBlock_Analog_Config[4];
	XRFdc_ADCBlock_DigitalDataPath_Config ADCBlock_Digital_Config[4];
} XRFdc_ADCTile_Config;

/**
 * RFdc Config Structure.
 */
typedef struct {
	u32 DeviceId;
	metal_phys_addr_t BaseAddr;
	u32 ADCType; /* ADC Type 4GSPS or 2GSPS*/
	u32 MasterADCTile; /* ADC master Tile */
	u32 MasterDACTile; /* DAC Master Tile */
	u32 ADCSysRefSource;
	u32 DACSysRefSource;
	u32 IPType;
	u32 SiRevision;
	XRFdc_DACTile_Config DACTile_Config[4];
	XRFdc_ADCTile_Config ADCTile_Config[4];
} XRFdc_Config;

/**
 * DAC Block Analog DataPath Structure.
 */
typedef struct {
	u32 Enabled; /* DAC Analog Data Path Enable */
	u32 MixedMode;
	double TerminationVoltage;
	double OutputCurrent;
	u32 InverseSincFilterEnable;
	u32 DecoderMode;
	void *FuncHandler;
	u32 NyquistZone;
	u8 AnalogPathEnabled;
	u8 AnalogPathAvailable;
	XRFdc_QMC_Settings QMC_Settings;
	XRFdc_CoarseDelay_Settings CoarseDelay_Settings;
} XRFdc_DACBlock_AnalogDataPath;

/**
 * DAC Block Digital DataPath Structure.
 */
typedef struct {
	u32 MixerInputDataType;
	u32 DataWidth;
	int ConnectedIData;
	int ConnectedQData;
	u32 InterpolationFactor;
	u8 DigitalPathEnabled;
	u8 DigitalPathAvailable;
	XRFdc_Mixer_Settings Mixer_Settings;
} XRFdc_DACBlock_DigitalDataPath;

/**
 * ADC Block Analog DataPath Structure.
 */
typedef struct {
	u32 Enabled; /* ADC Analog Data Path Enable */
	XRFdc_QMC_Settings QMC_Settings;
	XRFdc_CoarseDelay_Settings CoarseDelay_Settings;
	XRFdc_Threshold_Settings Threshold_Settings;
	u32 NyquistZone;
	u8 CalibrationMode;
	u8 AnalogPathEnabled;
	u8 AnalogPathAvailable;
} XRFdc_ADCBlock_AnalogDataPath;

/**
 * ADC Block Digital DataPath Structure.
 */
typedef struct {
	u32 MixerInputDataType;
	u32 DataWidth;
	u32 DecimationFactor;
	int ConnectedIData;
	int ConnectedQData;
	u8 DigitalPathEnabled;
	u8 DigitalPathAvailable;
	XRFdc_Mixer_Settings Mixer_Settings;
} XRFdc_ADCBlock_DigitalDataPath;

/**
 * DAC Tile Structure.
 */
typedef struct {
	u32 TileBaseAddr; /* Tile  BaseAddress*/
	u32 NumOfDACBlocks; /* Number of DAC block enabled */
	XRFdc_PLL_Settings PLL_Settings;
	u8 MultibandConfig;
	XRFdc_DACBlock_AnalogDataPath DACBlock_Analog_Datapath[4];
	XRFdc_DACBlock_DigitalDataPath DACBlock_Digital_Datapath[4];
} XRFdc_DAC_Tile;

/**
 * ADC Tile Structure.
 */
typedef struct {
	u32 TileBaseAddr;
	u32 NumOfADCBlocks; /* Number of ADC block enabled */
	XRFdc_PLL_Settings PLL_Settings;
	u8 MultibandConfig;
	XRFdc_ADCBlock_AnalogDataPath ADCBlock_Analog_Datapath[4];
	XRFdc_ADCBlock_DigitalDataPath ADCBlock_Digital_Datapath[4];
} XRFdc_ADC_Tile;

/**
 * RFdc Structure.
 */
typedef struct {
	XRFdc_Config RFdc_Config; /* Config Structure */
	u32 IsReady;
	u32 ADC4GSPS;
	metal_phys_addr_t BaseAddr; /* BaseAddress */
	struct metal_io_region *io; /* Libmetal IO structure */
	struct metal_device *device; /* Libmetal device structure */
	XRFdc_DAC_Tile DAC_Tile[4];
	XRFdc_ADC_Tile ADC_Tile[4];
	XRFdc_StatusHandler StatusHandler; /* Event handler function */
	void *CallBackRef; /* Callback reference for event handler */
	u8 UpdateMixerScale; /* Set to 1, if user overwrite mixer scale */
} XRFdc;