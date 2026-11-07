import React from 'react';
import {CoverColorPicker} from './cover_color_picker.jsx';
import {useColorDisclosure} from './common_color_swatches.jsx';
export {COMMON_COLORS,CommonColorPalette} from './common_color_swatches.jsx';

export function CommonColorOptions(props) {
  const disclosureRef=useColorDisclosure();
  const current=typeof props.value==='string'&&/^#[0-9a-f]{6}$/i.test(props.value)
    ?props.value:'#5672CA';
  const dismissAfterSelection=()=>{
    if(disclosureRef.current){
      disclosureRef.current.open=false;
      disclosureRef.current.querySelector(':scope > summary')?.focus();
    }
    props.onCommit?.();
  };
  return <details ref={disclosureRef} className="madar-common-colors__details">
    <summary aria-label={'انتخاب رنگ '+(props.label||'')}>
      <span className="madar-common-colors__preview" style={{backgroundColor:current}} aria-hidden="true"/>
      <span>رنگ</span>
    </summary>
    <CoverColorPicker {...props} onCommit={dismissAfterSelection}/>
  </details>;
}
