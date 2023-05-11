/*
 * rfdc_functions.h
 * Declarations of functions supported by pyxrfclk
 * Adapted from xrfdc.h
 */

typedef unsigned char u8;
typedef unsigned int u32;
typedef int s32;

#define XST_SUCCESS 0L
#define XST_FAILURE 1L


#define RFCLK_LMX2594_1 0 /* I0 on MUX and SS3 on Bridge */
#define RFCLK_LMX2594_2 1 /* I1 on MUX and SS2 on Bridge */
#define RFCLK_LMK 2 /* I2 on MUX and SS1 on Bridge */
#define RFCLK_CHIP_NUM 3
#define LMK_COUNT 128
#define LMK_FREQ_NUM 2 /* Number of LMK freq. configs */
#define LMX_ADC_NUM 8 /* Number of LMX ADC configs */
#define LMX_DAC_NUM 24 /* Number of LMX DAC configs */

#define LMX2594_COUNT 116
#define FREQ_LIST_STR_SIZE 50 /* Frequency string size */

u32 XRFClk_WriteReg(u32 ChipId, u32 Data);
u32 XRFClk_ReadReg(u32 ChipId, u32 *Data);
u32 XRFClk_Init(int GpioId);
void XRFClk_Close();
u32 XRFClk_ResetChip(u32 ChipId);
u32 XRFClk_SetConfigOnOneChipFromConfigId(u32 ChipId, u32 ConfigId);
u32 XRFClk_SetConfigOnOneChip(u32 ChipId, u32 *cfgData, u32 len);
u32 XRFClk_GetConfigFromOneChip(u32 ChipId, u32 *cfgData);
u32 XRFClk_SetConfigOnAllChipsFromConfigId(u32 ConfigId_LMK, u32 ConfigId_RF1, u32 ConfigId_RF2);
u32 XRFClk_ControlOutputPortLMK(u32 PortId, u32 state);
u32 XRFClk_ConfigOutputDividerAndMUXOnLMK(u32 PortId, u32 DCLKoutX_DIV, u32 DCLKoutX_MUX, u32 SDCLKoutY_MUX, u32 SYSREF_DIV);

