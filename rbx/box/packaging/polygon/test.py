from rbx.box.packaging.polygon import xml_schema as polygon_schema

if __name__ == '__main__':
    print(
        polygon_schema.Problem.from_xml("""
<problem>
  <names>
    <name language="english" value="Poliedro"/>
    <name language="portuguese" value="Poliedro"/>
  </names>
  <statements>
    <statement charset="UTF-8" language="english" mathjax="true" path="statements/english/problem.tex" type="application/x-tex"/>
    <statement charset="UTF-8" language="portuguese" mathjax="true" path="statements/portuguese/problem.tex" type="application/x-tex"/>
    <statement charset="UTF-8" language="english" mathjax="true" path="statements/.html/english/problem.html" type="text/html"/>
    <statement charset="UTF-8" language="portuguese" mathjax="true" path="statements/.html/portuguese/problem.html" type="text/html"/>
    <statement language="english" path="statements/.pdf/english/problem.pdf" type="application/pdf"/>
    <statement language="portuguese" path="statements/.pdf/portuguese/problem.pdf" type="application/pdf"/>
  </statements>
  <judging input-file="" output-file="">
    <testset name="tests">
      <time-limit>1000</time-limit>
      <memory-limit>268435456</memory-limit>
      <test-count>13</test-count>
      <input-path-pattern>tests/%02d</input-path-pattern>
      <answer-path-pattern>tests/%02d.a</answer-path-pattern>
      <tests>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
        <test method="manual"/>
      </tests>
    </testset>
  </judging>
  <files>
    <resources>
      <file path="files/jngen.h" type="h.g++"/>
      <file path="files/olymp.sty"/>
      <file path="files/problem.tex"/>
      <file path="files/statements.ftl"/>
      <file path="files/testlib.h" type="h.g++"/>
      <file path="files/tgen.h" type="h.g++"/>
    </resources>
  </files>
  <assets>
    <checker name="std::ncmp.cpp" type="testlib">
      <source path="files/check.cpp" type="cpp.g++17"/>
      <binary path="check.exe" type="exe.win32"/>
      <copy path="check.cpp"/>
    </checker>                              
  </assets>                                       
</problem>
""")
    )

    print(
        polygon_schema.Contest.from_xml("""
<contest>
<names>
<name language="russian" main="true" value="2012-2013 Тренировка СПбГУ B #12 Бинарный поиск, тернарный поиск"/>
</names>
<statements>
<statement language="russian" path="statements/russian/20122013-tryenirovka-spbgu-b-12-binarnyy-poisk-tyernarnyy-poisk-ru.pdf" type="application/pdf"/>
</statements>
<problems>
<problem index="A" path="problems/A"/>
<problem index="B" path="problems/B"/>
<problem index="C" path="problems/C"/>
<problem index="D" path="problems/D"/>
<problem index="E" path="problems/E"/>
</problems>
</contest>
""")
    )
