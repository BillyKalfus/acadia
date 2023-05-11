typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef signed int s32;
typedef signed short s16;
typedef unsigned long u64;
typedef signed long s64;
typedef unsigned long metal_phys_addr_t;

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
	u8 SourceTile;
	u8 PLLEnable;
	XRFdc_PLL_Settings PLLSettings;
	u8 DivisionFactor;
	u8 Delay;
	u8 DistributedClock;
} XRFdc_Tile_Clock_Settings;
/**
* Clk Distribution.
*/
typedef struct {
	u8 Enabled;
	u8 DistributionSource;
	u8 UpperBound;
	u8 LowerBound;
	u8 MaxDelay;
	u8 MinDelay;
	u8 IsDelayBalanced;
} XRFdc_Distribution;
/**
* Clk Distribution Settings.
*/
typedef struct {
	XRFdc_Tile_Clock_Settings DAC[4];
	XRFdc_Tile_Clock_Settings ADC[4];
	XRFdc_Distribution DistributionStatus[8];
} XRFdc_Distribution_Settings;

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
