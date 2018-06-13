open LogoLib
open LogoInterpreter

let pi2 = 2. *. 3.1459

let rec unfold f stop b =
if stop b then []
else 
  let x, b' = f b in
   x :: (unfold f stop b')

let star (n : int) : turtle =
  List.fold_left
    (fun (k : turtle) (e : float) : turtle ->
      logo_SEQ
        k
        (logo_SEQ
          (logo_GET
            (fun s ->
              logo_SEQ
                (logo_FW 100.)
                (logo_SET s)
            )
          )
          (logo_RT e)
        )
    )
    logo_NOP
    (List.map
      (fun _ -> pi2 /. (float_of_int n))
      (unfold
        (fun x -> (x, x + 1))
        (fun x -> x >= n)
        0
      )
    )

let line : turtle =
  logo_FW logo_var_UNIT

let angle : turtle =
  logo_SEQ
    (logo_FW logo_var_UNIT)
    (logo_SEQ
      (logo_RT (logo_var_HLF logo_var_UNIT))
      (logo_FW logo_var_UNIT))

let square1 : turtle =
  let angle =
    logo_SEQ
      (logo_FW logo_var_UNIT)
      (logo_RT (logo_var_HLF logo_var_UNIT))
  in
  let half = logo_SEQ angle angle in
  logo_SEQ half half

let square2 : turtle =
  let angle =
    logo_SEQ
      (logo_FW logo_var_UNIT)
      (logo_RT (logo_var_HLF logo_var_UNIT)) in
  List.fold_left
    (fun (k : turtle) (e : float) : turtle ->
      logo_SEQ
        k
        angle
    )
    logo_NOP
    ([0.; 1.; 2.; 3.])


let _ =
  let c1 = eval_turtle line in
  let c2 = eval_turtle angle in
  let c3 = eval_turtle square1 in
  let c4 = eval_turtle square2 in
  pp_turtle square1;
  pp_turtle square2;
  VGWrapper.output_canvas_png c1 28 "line_l.png" ;
  VGWrapper.output_canvas_png c2 28 "angle_l.png" ;
  VGWrapper.output_canvas_png c3 28 "square1_l.png" ;
  VGWrapper.output_canvas_png c4 28 "square2_l.png" ;
  print_endline "done"
